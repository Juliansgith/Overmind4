from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


HARNESS_PREFIX = "OM4HARNESS|"
OVERMIND_PREFIX = "OM4|"
TERMINAL_RESULTS = {"victory", "defeat", "draw"}


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
    sim_timeout: bool = False


@dataclass(frozen=True)
class WarningDetail:
    code: str
    source: str
    archive: str
    path: str
    line: int
    method: str
    occurrences: int


@dataclass(frozen=True)
class LifecycleStatus:
    valid: bool
    reason: str | None
    harness_start_seen: bool
    harness_speed_seen: bool
    brain_created_seen: bool
    brain_begin_session_seen: bool
    brain_terminal_result: str | None
    events: tuple[str, ...]


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
    lifecycle: LifecycleStatus
    engine_diagnostics: tuple[str, ...] = ()
    engine_diagnostic_before_lifecycle: bool = False
    engine_diagnostic_before_result: bool = False
    result_integrity_reason: str | None = None
    harness_failure_reason: str | None = None
    warning_details: tuple[WarningDetail, ...] = ()


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
    lifecycle: LifecycleStatus
    warnings: tuple[str, ...] = ()
    warning_details: tuple[WarningDetail, ...] = ()


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


_LOG_PREFIX = re.compile(r"^\s*(?:(?:debug|info|warning|error):\s*)?", re.IGNORECASE)
FAF_STOCK_PLATOON_DISBAND_WARNING = "faf-stock-platoon-disband-nil"
_STOCK_PLATOON_PATH_PATTERN = (
    r"\.\.\.ogramdata\\faforever\\gamedata\\lua\.nx2\\lua\\platoon\.lua"
)
_STOCK_PLATOON_WARNING_HEADER = re.compile(
    r"^\s*warning:\s*Error running lua script:\s+"
    + _STOCK_PLATOON_PATH_PATTERN
    + r"\(2363\): attempt to call method `PlatoonDisband' \(a nil value\)\s*$"
)
_STOCK_PLATOON_TRACEBACK_LABEL = re.compile(r"^\s+stack traceback:\s*$")
_STOCK_PLATOON_TRACE_FRAME = re.compile(
    r"^\s+"
    + _STOCK_PLATOON_PATH_PATTERN
    + r"\(2363\): in function <"
    + _STOCK_PLATOON_PATH_PATTERN
    + r":2210>\s*$"
)
_ENGINE_FAILURES = (
    (re.compile(r"LUA ERROR(?=\s|:|$)", re.IGNORECASE), "lua-error"),
    (
        re.compile(r"ERROR RUNNING LUA SCRIPT(?=\s|:|$)", re.IGNORECASE),
        "lua-error",
    ),
    (
        re.compile(
            r"ERROR RUNNING ONFRAME SCRIPT IN CSCRIPTOBJECT AT \S+:\s",
            re.IGNORECASE,
        ),
        "lua-error",
    ),
    (re.compile(r"ERROR IMPORTING(?=\s|:|$)", re.IGNORECASE), "import-error"),
    (re.compile(r"UNABLE TO LOAD MAP(?=\s|:|$)", re.IGNORECASE), "map-load-error"),
    (re.compile(r"DESYNC(?=\s|:|$)", re.IGNORECASE), "desync"),
    (
        re.compile(r"EXCEPTION_ACCESS_VIOLATION(?=\s|:|$)", re.IGNORECASE),
        "engine-crash",
    ),
)


def is_stock_platoon_warning_header(line: str) -> bool:
    return _STOCK_PLATOON_WARNING_HEADER.fullmatch(line) is not None


def is_stock_platoon_traceback_label(line: str) -> bool:
    return _STOCK_PLATOON_TRACEBACK_LABEL.fullmatch(line) is not None


def is_stock_platoon_trace_frame(line: str) -> bool:
    return _STOCK_PLATOON_TRACE_FRAME.fullmatch(line) is not None


def is_trace_continuation(line: str) -> bool:
    return bool(line) and line[0].isspace()


def _stock_platoon_warning_ranges(lines: list[str]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not is_stock_platoon_warning_header(line):
            continue
        trace_end = index + 3
        if trace_end > len(lines):
            continue
        if not is_stock_platoon_traceback_label(lines[index + 1]):
            continue
        if not is_stock_platoon_trace_frame(lines[index + 2]):
            continue
        next_content = trace_end
        while next_content < len(lines) and not lines[next_content].strip():
            next_content += 1
        if next_content < len(lines) and is_trace_continuation(lines[next_content]):
            continue
        ranges.append((index, next_content))
    return tuple(ranges)


def _fields_at_prefix(line: str, prefix: str) -> dict[str, str] | None:
    log_prefix = _LOG_PREFIX.match(line)
    marker_at = log_prefix.end() if log_prefix else 0
    if not line.startswith(prefix, marker_at):
        return None
    fields: dict[str, str] = {}
    for token in line[marker_at:].strip().split("|")[1:]:
        if "=" in token:
            name, value = token.split("=", 1)
            fields[name] = value
    return fields


def _marker_fields(line: str) -> dict[str, str] | None:
    return _fields_at_prefix(line, HARNESS_PREFIX)


def harness_marker_fields(line: str) -> dict[str, str] | None:
    return _marker_fields(line)


def _overmind_fields(line: str) -> dict[str, str] | None:
    return _fields_at_prefix(line, OVERMIND_PREFIX)


def overmind_marker_fields(line: str) -> dict[str, str] | None:
    return _overmind_fields(line)


def _number(value: str | None) -> float | None:
    try:
        number = float(value) if value is not None else None
    except ValueError:
        return None
    if number is None or number < 0:
        return None
    return number


def detect_engine_failure(text: str) -> str | None:
    for line in text.splitlines():
        log_prefix = _LOG_PREFIX.match(line)
        payload = line[log_prefix.end() :] if log_prefix else line
        for pattern, reason in _ENGINE_FAILURES:
            if pattern.match(payload):
                return reason
    return None


def parse_log(text: str, run_id: str, our_slot: int) -> LogTelemetry:
    official_result: str | None = None
    sim_seconds: float | None = None
    requested_speed: float | None = None
    sim_timeout = False
    harness_failure_reason: str | None = None
    positions: dict[str, int] = {}
    events: list[str] = []
    brain_terminal_result: str | None = None
    official_results: list[str] = []
    brain_terminal_results: list[str] = []
    engine_diagnostics_with_lines: list[tuple[int, str]] = []
    lines = text.splitlines()
    stock_warning_ranges = _stock_platoon_warning_ranges(lines)
    stock_warning_headers = {start for start, _ in stock_warning_ranges}

    for line_number, line in enumerate(lines):
        engine_diagnostic = (
            None
            if line_number in stock_warning_headers
            else detect_engine_failure(line)
        )
        if engine_diagnostic:
            engine_diagnostics_with_lines.append((line_number, engine_diagnostic))

        brain_fields = _overmind_fields(line)
        if (
            brain_fields
            and brain_fields.get("v") == "1"
            and brain_fields.get("kind") == "lifecycle"
        ):
            try:
                brain_army = int(brain_fields.get("army", ""))
            except ValueError:
                brain_army = -1
            if brain_army == our_slot:
                event = brain_fields.get("event")
                event_name = {
                    "created": "brain_created",
                    "begin_session": "brain_begin_session",
                }.get(event or "")
                if event_name and event_name not in positions:
                    positions[event_name] = line_number
                    events.append(event_name)
                elif event == "terminal":
                    terminal = (brain_fields.get("result") or "").lower()
                    if terminal in TERMINAL_RESULTS:
                        brain_terminal_results.append(terminal)
                        if brain_terminal_result is None:
                            brain_terminal_result = terminal
                            positions["brain_terminal"] = line_number
                        events.append(f"brain_terminal:{terminal}")

        fields = _marker_fields(line)
        if not fields or fields.get("run") != run_id or fields.get("v") != "1":
            continue
        kind = fields.get("kind")
        marker_sim = _number(fields.get("sim"))
        if marker_sim is not None:
            sim_seconds = marker_sim
        if kind == "start" and "harness_start" not in positions:
            positions["harness_start"] = line_number
            events.append("harness_start")
        elif kind == "speed":
            marker_speed = _number(fields.get("requested"))
            if marker_speed is not None and "harness_speed" not in positions:
                requested_speed = marker_speed
                positions["harness_speed"] = line_number
                events.append("harness_speed")
        elif kind == "timeout":
            sim_timeout = True
        elif kind == "failure":
            harness_failure_reason = fields.get("reason") or "harness-failure"
        elif kind == "result":
            result = fields.get("result")
            result_kind = (result or "").split(" ", 1)[0].lower()
            if result_kind in TERMINAL_RESULTS and "first_harness_result" not in positions:
                positions["first_harness_result"] = line_number
            try:
                army = int(fields.get("army", ""))
            except ValueError:
                continue
            if army == our_slot and result_kind in TERMINAL_RESULTS:
                official_results.append(result or result_kind)
                if official_result is None:
                    official_result = result
                    positions["official_result"] = line_number
                    events.append("official_result")

    required = (
        "harness_start",
        "brain_created",
        "brain_begin_session",
        "harness_speed",
    )
    if "harness_start" not in positions:
        lifecycle_reason = "missing-harness-start"
    elif "brain_created" not in positions:
        lifecycle_reason = "fallback-brain"
    elif "brain_begin_session" not in positions:
        lifecycle_reason = "missing-brain-begin-session"
    elif "harness_speed" not in positions:
        lifecycle_reason = "missing-harness-speed"
    elif [positions[name] for name in required] != sorted(positions[name] for name in required):
        lifecycle_reason = "lifecycle-out-of-order"
    elif (
        "official_result" in positions
        and positions["official_result"] < positions["harness_speed"]
    ):
        lifecycle_reason = "lifecycle-out-of-order"
    elif (
        "brain_terminal" in positions
        and positions["brain_terminal"] < positions["harness_speed"]
    ):
        lifecycle_reason = "lifecycle-out-of-order"
    else:
        lifecycle_reason = None

    lifecycle = LifecycleStatus(
        valid=lifecycle_reason is None,
        reason=lifecycle_reason,
        harness_start_seen="harness_start" in positions,
        harness_speed_seen="harness_speed" in positions,
        brain_created_seen="brain_created" in positions,
        brain_begin_session_seen="brain_begin_session" in positions,
        brain_terminal_result=brain_terminal_result,
        events=tuple(events),
    )

    accepted_stock_warning_count = 0
    lifecycle_completion_line = positions.get("harness_speed")
    for warning_line, _ in stock_warning_ranges:
        if (
            lifecycle.valid
            and lifecycle_completion_line is not None
            and warning_line > lifecycle_completion_line
        ):
            accepted_stock_warning_count += 1
        else:
            engine_diagnostics_with_lines.append((warning_line, "lua-error"))

    engine_diagnostics_with_lines.sort(key=lambda item: item[0])
    warning_details = (
        (
            WarningDetail(
                code=FAF_STOCK_PLATOON_DISBAND_WARNING,
                source="FAF stock",
                archive="gamedata/lua.nx2",
                path="lua/platoon.lua",
                line=2363,
                method="PlatoonDisband",
                occurrences=accepted_stock_warning_count,
            ),
        )
        if accepted_stock_warning_count
        else ()
    )

    if len(official_results) > 1:
        official_kinds = {
            result.lower().split(" ", 1)[0] for result in official_results
        }
        result_integrity_reason = (
            "conflicting-official-results"
            if len(official_kinds) > 1
            else "duplicate-official-result"
        )
    elif len(brain_terminal_results) > 1:
        terminal_kinds = set(brain_terminal_results)
        result_integrity_reason = (
            "conflicting-brain-terminals"
            if len(terminal_kinds) > 1
            else "duplicate-brain-terminal"
        )
    elif official_result and brain_terminal_result:
        official_kind = official_result.lower().split(" ", 1)[0]
        result_integrity_reason = (
            None
            if official_kind == brain_terminal_result
            else "terminal-result-mismatch"
        )
    else:
        result_integrity_reason = None

    engine_diagnostics = tuple(
        dict.fromkeys(reason for _, reason in engine_diagnostics_with_lines)
    )
    harness_speed_line = positions.get("harness_speed")
    engine_diagnostic_before_lifecycle = bool(engine_diagnostics_with_lines) and (
        harness_speed_line is None
        or any(line_number < harness_speed_line for line_number, _ in engine_diagnostics_with_lines)
    )
    first_harness_result_line = positions.get("first_harness_result")
    engine_diagnostic_before_result = bool(engine_diagnostics_with_lines) and (
        first_harness_result_line is None
        or any(
            line_number < first_harness_result_line
            for line_number, _ in engine_diagnostics_with_lines
        )
    )
    failure_reason = harness_failure_reason or (
        engine_diagnostics[0] if engine_diagnostics else None
    )

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
        lifecycle=lifecycle,
        engine_diagnostics=engine_diagnostics,
        engine_diagnostic_before_lifecycle=engine_diagnostic_before_lifecycle,
        engine_diagnostic_before_result=engine_diagnostic_before_result,
        result_integrity_reason=result_integrity_reason,
        harness_failure_reason=harness_failure_reason,
        warning_details=warning_details,
    )


def _state_for_failure(reason: str) -> str:
    lowered = reason.lower()
    if lowered == "desync":
        return "desync"
    if (
        lowered == "engine-crash"
        or lowered == "termination-failure"
        or lowered.startswith("process-launch-error")
        or lowered.startswith("process-monitor-error")
        or lowered.startswith("preferences-")
    ):
        return "crash"
    return "load-error"


def classify_outcome(telemetry: LogTelemetry, process: ProcessObservation) -> Outcome:
    process_reason = process.fail_fast_reason
    safety_failure = process_reason == "termination-failure" or bool(
        process_reason and process_reason.startswith("preferences-")
    )
    official_kind = (
        telemetry.official_result.lower().split(" ", 1)[0]
        if telemetry.official_result
        else None
    )
    corroborated_result = (
        telemetry.lifecycle.valid
        and telemetry.result_integrity_reason is None
        and official_kind in TERMINAL_RESULTS
        and telemetry.lifecycle.brain_terminal_result == official_kind
    )
    telemetry_failure_is_engine_diagnostic = (
        telemetry.failure_reason is not None
        and telemetry.failure_reason in telemetry.engine_diagnostics
    )
    process_failure_is_same_engine_diagnostic = process_reason is None or (
        process_reason in telemetry.engine_diagnostics
    )
    recoverable_engine_diagnostic = (
        corroborated_result
        and telemetry.harness_failure_reason is None
        and telemetry_failure_is_engine_diagnostic
        and process_failure_is_same_engine_diagnostic
        and not telemetry.engine_diagnostic_before_lifecycle
        and not telemetry.engine_diagnostic_before_result
    )
    structured_warning_codes = tuple(
        warning.code for warning in telemetry.warning_details
    )
    warnings = tuple(
        dict.fromkeys(
            structured_warning_codes
            + (telemetry.engine_diagnostics if recoverable_engine_diagnostic else ())
        )
    )
    structured_warning_corroborates_exit = (
        corroborated_result
        and bool(telemetry.warning_details)
        and telemetry.harness_failure_reason is None
        and telemetry.failure_reason is None
        and process_reason is None
    )

    if safety_failure:
        failure_reason = process_reason
    else:
        failure_reason = telemetry.failure_reason or process_reason
    if recoverable_engine_diagnostic:
        failure_reason = None

    if safety_failure:
        state = _state_for_failure(failure_reason or "termination-failure")
    elif failure_reason:
        state = _state_for_failure(failure_reason)
    elif telemetry.sim_timeout or process.sim_timeout:
        if not telemetry.lifecycle.valid:
            failure_reason = telemetry.lifecycle.reason
            state = "load-error"
        else:
            state = "sim-timeout"
    elif process.wall_timeout:
        state = "wall-timeout"
    elif (
        process.exit_code not in (0, None)
        and not recoverable_engine_diagnostic
        and not structured_warning_corroborates_exit
    ):
        state = "crash"
    elif (
        process.exit_code is None
        and not telemetry.sim_timeout
        and not recoverable_engine_diagnostic
        and not structured_warning_corroborates_exit
    ):
        state = "crash"
    elif not telemetry.lifecycle.valid:
        failure_reason = telemetry.lifecycle.reason
        state = "load-error"
    elif telemetry.result_integrity_reason:
        failure_reason = telemetry.result_integrity_reason
        state = "malformed"
    elif telemetry.json_stats_malformed:
        state = "malformed"
    elif telemetry.official_result:
        normalized = telemetry.official_result.lower().split(" ", 1)[0]
        if normalized == "victory":
            state = "win"
        elif normalized == "defeat":
            state = "loss"
        elif normalized == "draw":
            state = "draw"
        else:
            state = "malformed"
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
        lifecycle=telemetry.lifecycle,
        warnings=warnings,
        warning_details=telemetry.warning_details,
    )
