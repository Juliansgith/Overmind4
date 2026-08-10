from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


HARNESS_PREFIX = "OM4HARNESS|"


@dataclass(frozen=True)
class JsonStatsResult:
    value: dict[str, Any] | None
    seen: bool
    malformed: bool


@dataclass(frozen=True)
class ProcessObservation:
    exit_code: int | None
    wall_seconds: float
    wall_timeout: bool = False
    fail_fast_reason: str | None = None


@dataclass(frozen=True)
class LogTelemetry:
    official_result: str | None
    sim_seconds: float | None
    requested_speed: float | None
    sim_timeout: bool
    failure_reason: str | None
    json_stats: dict[str, Any] | None
    json_stats_seen: bool
    json_stats_malformed: bool


@dataclass(frozen=True)
class Outcome:
    state: str
    is_win: bool
    exit_code: int | None
    wall_seconds: float
    sim_seconds: float | None
    requested_speed: float | None
    achieved_sim_speed: float | None
    official_result: str | None
    failure_reason: str | None
    json_stats: dict[str, Any] | None


def _balanced_json_object(text: str, start: int) -> tuple[str | None, int]:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1], index + 1
    return None, len(text)


def extract_json_stats(text: str) -> JsonStatsResult:
    positions = [match.end() for match in re.finditer(r"JsonStats\s*", text)]
    if not positions:
        return JsonStatsResult(value=None, seen=False, malformed=False)

    valid: dict[str, Any] | None = None
    for payload_start in positions:
        line_end = text.find("\n", payload_start)
        search_end = len(text) if line_end < 0 else line_end
        object_start = text.find("{", payload_start, search_end)
        if object_start < 0:
            continue
        payload, _ = _balanced_json_object(text, object_start)
        if payload is None:
            continue
        try:
            candidate = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            valid = candidate

    return JsonStatsResult(value=valid, seen=True, malformed=valid is None)


def _marker_fields(line: str) -> dict[str, str] | None:
    marker_at = line.find(HARNESS_PREFIX)
    if marker_at < 0:
        return None
    fields: dict[str, str] = {}
    for token in line[marker_at:].strip().split("|")[1:]:
        if "=" in token:
            name, value = token.split("=", 1)
            fields[name] = value
    return fields


def _number(value: str | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except ValueError:
        return None
    if number is None or number < 0:
        return None
    return number


def _generic_failure(text: str) -> str | None:
    lowered = text.lower()
    patterns = (
        ("desync", "desync"),
        ("lua error", "lua-error"),
        ("error importing", "import-error"),
        ("unable to load map", "map-load-error"),
        ("exception_access_violation", "engine-crash"),
    )
    for needle, reason in patterns:
        if needle in lowered:
            return reason
    return None


def parse_log(text: str, run_id: str, our_slot: int) -> LogTelemetry:
    official_result: str | None = None
    sim_seconds: float | None = None
    requested_speed: float | None = None
    sim_timeout = False
    failure_reason = _generic_failure(text)

    for line in text.splitlines():
        fields = _marker_fields(line)
        if not fields or fields.get("run") != run_id or fields.get("v") != "1":
            continue
        kind = fields.get("kind")
        marker_sim = _number(fields.get("sim"))
        if marker_sim is not None:
            sim_seconds = marker_sim
        if kind == "speed":
            requested_speed = _number(fields.get("requested"))
        elif kind == "timeout":
            sim_timeout = True
        elif kind == "failure":
            failure_reason = fields.get("reason") or "harness-failure"
        elif kind == "result":
            try:
                army = int(fields.get("army", ""))
            except ValueError:
                failure_reason = "malformed-result-marker"
                continue
            if army == our_slot:
                official_result = fields.get("result")

    stats = extract_json_stats(text)
    return LogTelemetry(
        official_result=official_result,
        sim_seconds=sim_seconds,
        requested_speed=requested_speed,
        sim_timeout=sim_timeout,
        failure_reason=failure_reason,
        json_stats=stats.value,
        json_stats_seen=stats.seen,
        json_stats_malformed=stats.malformed,
    )


def classify_outcome(telemetry: LogTelemetry, process: ProcessObservation) -> Outcome:
    failure_reason = telemetry.failure_reason or process.fail_fast_reason
    if process.wall_timeout:
        state = "wall-timeout"
    elif failure_reason:
        state = "load-error"
    elif telemetry.sim_timeout:
        state = "sim-timeout"
    elif telemetry.json_stats_malformed:
        state = "malformed"
    elif process.exit_code not in (0, None):
        state = "crash"
    elif telemetry.official_result:
        normalized = telemetry.official_result.lower()
        if "victory" in normalized:
            state = "win"
        elif "defeat" in normalized:
            state = "loss"
        elif "draw" in normalized:
            state = "draw"
        else:
            state = "malformed"
    elif process.exit_code is None:
        state = "crash"
    else:
        state = "missing-result"

    achieved = None
    if telemetry.sim_seconds is not None and process.wall_seconds > 0:
        achieved = telemetry.sim_seconds / process.wall_seconds
    return Outcome(
        state=state,
        is_win=state == "win",
        exit_code=process.exit_code,
        wall_seconds=process.wall_seconds,
        sim_seconds=telemetry.sim_seconds,
        requested_speed=telemetry.requested_speed,
        achieved_sim_speed=achieved,
        official_result=telemetry.official_result,
        failure_reason=failure_reason,
        json_stats=telemetry.json_stats,
    )

