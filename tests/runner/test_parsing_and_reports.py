from __future__ import annotations

import json

import pytest

from tools.overmind4_runner.parsing import (
    ProcessObservation,
    classify_outcome,
    extract_json_stats,
    parse_log,
)
from tools.overmind4_runner.reporting import render_json, render_markdown


def _result_line(result: str, *, army: int = 1, sim: int = 123) -> str:
    return (
        "info: OM4HARNESS|v=1|kind=result|run=run-1|army="
        f"{army}|result={result}|sim={sim}\n"
    )


def test_json_stats_parser_handles_braces_inside_quoted_strings() -> None:
    text = 'debug: JsonStats {"stats":[{"name":"AI } { quoted","score":7}]} tail\n'

    parsed = extract_json_stats(text)

    assert parsed.value == {"stats": [{"name": "AI } { quoted", "score": 7}]}
    assert parsed.seen is True
    assert parsed.malformed is False


def test_json_stats_parser_uses_last_complete_payload_among_multiple_lines() -> None:
    text = (
        'JsonStats {"stats":[{"score":1}]}\n'
        'unrelated {not json}\n'
        'JsonStats {"stats":[{"score":2}]}\n'
    )

    assert extract_json_stats(text).value["stats"][0]["score"] == 2


@pytest.mark.parametrize(
    "text",
    [
        'JsonStats {"stats":[',
        'JsonStats {not-json}',
        'JsonStats "not-an-object"',
    ],
)
def test_json_stats_parser_marks_truncated_or_malformed_payloads(text: str) -> None:
    parsed = extract_json_stats(text)

    assert parsed.value is None
    assert parsed.seen is True
    assert parsed.malformed is True


def test_log_parser_ignores_markers_for_another_run() -> None:
    text = (
        "OM4HARNESS|v=1|kind=result|run=unrelated|army=1|result=victory|sim=9\n"
        + _result_line("defeat")
    )

    telemetry = parse_log(text, "run-1", our_slot=1)

    assert telemetry.official_result == "defeat"
    assert telemetry.sim_seconds == 123


@pytest.mark.parametrize(
    ("result", "expected"),
    [("victory 10", "win"), ("defeat 10", "loss"), ("draw", "draw")],
)
def test_official_result_maps_to_explicit_outcome(result: str, expected: str) -> None:
    telemetry = parse_log(_result_line(result), "run-1", our_slot=1)

    outcome = classify_outcome(
        telemetry,
        ProcessObservation(exit_code=0, wall_seconds=4.0),
    )

    assert outcome.state == expected
    assert outcome.is_win is (expected == "win")


def test_sim_timeout_has_priority_over_later_ui_result() -> None:
    text = (
        "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n"
        + _result_line("draw", sim=1800)
    )
    telemetry = parse_log(text, "run-1", our_slot=1)

    outcome = classify_outcome(telemetry, ProcessObservation(exit_code=0, wall_seconds=80))

    assert outcome.state == "sim-timeout"
    assert outcome.is_win is False


def test_wall_timeout_is_an_operational_failure_and_non_win() -> None:
    telemetry = parse_log("", "run-1", our_slot=1)

    outcome = classify_outcome(
        telemetry,
        ProcessObservation(exit_code=None, wall_seconds=300, wall_timeout=True),
    )

    assert outcome.state == "wall-timeout"
    assert outcome.is_win is False


@pytest.mark.parametrize(
    ("text", "exit_code", "expected"),
    [
        ("warning: LUA ERROR: import failed\n", 1, "load-error"),
        ("info: DESYNC detected\n", 0, "load-error"),
        ("OM4HARNESS|v=1|kind=failure|run=run-1|reason=mod_missing\n", 1, "load-error"),
        ("", -1, "crash"),
        ('JsonStats {"stats":[', 0, "malformed"),
        ("", 0, "missing-result"),
    ],
)
def test_operational_failures_have_distinct_states(text: str, exit_code: int, expected: str) -> None:
    telemetry = parse_log(text, "run-1", our_slot=1)

    outcome = classify_outcome(
        telemetry,
        ProcessObservation(exit_code=exit_code, wall_seconds=2),
    )

    assert outcome.state == expected
    assert outcome.is_win is False


def test_missing_telemetry_uses_null_not_numeric_zero() -> None:
    outcome = classify_outcome(
        parse_log("", "run-1", our_slot=1),
        ProcessObservation(exit_code=0, wall_seconds=2),
    )
    document = json.loads(render_json(outcome, run_id="run-1"))

    assert document["sim_seconds"] is None
    assert document["requested_speed"] is None
    assert document["achieved_sim_speed"] is None
    assert "0" not in render_markdown(outcome, run_id="run-1").split("Simulation seconds: ", 1)[1].splitlines()[0]


def test_reports_are_deterministic_and_concise() -> None:
    telemetry = parse_log(
        "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
        + _result_line("victory", sim=100),
        "run-1",
        our_slot=1,
    )
    outcome = classify_outcome(telemetry, ProcessObservation(exit_code=0, wall_seconds=4))

    assert render_json(outcome, run_id="run-1") == render_json(outcome, run_id="run-1")
    markdown = render_markdown(outcome, run_id="run-1")
    assert markdown == render_markdown(outcome, run_id="run-1")
    assert "WIN" in markdown
    assert "25.00x" in markdown
    assert len(markdown.splitlines()) < 20

