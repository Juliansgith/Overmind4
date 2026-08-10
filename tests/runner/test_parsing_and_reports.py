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


def _valid_lifecycle_prefix(*, army: int = 1) -> str:
    return (
        "OM4HARNESS|v=1|kind=start|run=run-1|map=SCMP_007\n"
        f"OM4|v=1|kind=lifecycle|army={army}|event=created|plan=none\n"
        f"OM4|v=1|kind=lifecycle|army={army}|event=begin_session\n"
        "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
    )


def _valid_match(result: str, *, army: int = 1, sim: int = 123) -> str:
    return _valid_lifecycle_prefix(army=army) + _result_line(
        result, army=army, sim=sim
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
    telemetry = parse_log(_valid_match(result), "run-1", our_slot=1)

    outcome = classify_outcome(
        telemetry,
        ProcessObservation(exit_code=0, wall_seconds=4.0),
    )

    assert outcome.state == expected
    assert outcome.is_win is (expected == "win")


def test_sim_timeout_has_priority_over_later_ui_result() -> None:
    text = (
        _valid_lifecycle_prefix()
        +
        "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n"
        + _result_line("draw", sim=1800)
    )
    telemetry = parse_log(text, "run-1", our_slot=1)

    outcome = classify_outcome(telemetry, ProcessObservation(exit_code=0, wall_seconds=80))

    assert outcome.state == "sim-timeout"
    assert outcome.is_win is False


def test_result_parser_ignores_score_and_keeps_first_valid_terminal_result() -> None:
    text = (
        _valid_lifecycle_prefix()
        + _result_line("score 99")
        + _result_line("victory 10")
        + _result_line("defeat 10")
    )

    telemetry = parse_log(text, "run-1", our_slot=1)

    assert telemetry.official_result == "victory 10"


def test_valid_match_records_required_lifecycle_presence_order_and_terminal_diagnostic() -> None:
    text = (
        _valid_match("victory 10")
        + "OM4|v=1|kind=lifecycle|army=1|event=terminal|result=victory\n"
    )

    telemetry = parse_log(text, "run-1", our_slot=1)

    assert telemetry.lifecycle.valid is True
    assert telemetry.lifecycle.reason is None
    assert telemetry.lifecycle.events == (
        "harness_start",
        "brain_created",
        "brain_begin_session",
        "harness_speed",
        "official_result",
        "brain_terminal:victory",
    )
    assert telemetry.lifecycle.brain_terminal_result == "victory"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (
            "OM4|v=1|kind=lifecycle|army=1|event=created\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            + _result_line("victory"),
            "missing-harness-start",
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            + _result_line("victory"),
            "fallback-brain",
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "OM4|v=1|kind=lifecycle|army=1|event=created\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            + _result_line("victory"),
            "lifecycle-out-of-order",
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1\n"
            "OM4|v=1|kind=lifecycle|army=2|event=created\n"
            "OM4|v=1|kind=lifecycle|army=2|event=begin_session\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            + _result_line("victory"),
            "fallback-brain",
        ),
    ],
)
def test_result_is_rejected_when_required_lifecycle_is_missing_or_out_of_order(
    text: str, reason: str
) -> None:
    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(exit_code=0, wall_seconds=4),
    )

    assert outcome.state == "load-error"
    assert outcome.is_win is False
    assert outcome.failure_reason == reason


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
        ("info: DESYNC detected\n", 0, "desync"),
        ("OM4HARNESS|v=1|kind=failure|run=run-1|reason=mod_missing\n", 1, "load-error"),
        ("EXCEPTION_ACCESS_VIOLATION\n", 1, "crash"),
        ("", -1, "crash"),
        (_valid_lifecycle_prefix() + 'JsonStats {"stats":[', 0, "malformed"),
        (_valid_lifecycle_prefix(), 0, "missing-result"),
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
    telemetry = parse_log(_valid_match("victory", sim=100), "run-1", our_slot=1)
    outcome = classify_outcome(telemetry, ProcessObservation(exit_code=0, wall_seconds=4))

    assert render_json(outcome, run_id="run-1") == render_json(outcome, run_id="run-1")
    markdown = render_markdown(outcome, run_id="run-1")
    assert markdown == render_markdown(outcome, run_id="run-1")
    assert "WIN" in markdown
    assert "25.00x" in markdown
    assert len(markdown.splitlines()) < 20


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("lua-error", "load-error"),
        ("import-error", "load-error"),
        ("map-load-error", "load-error"),
        ("mod_unavailable", "load-error"),
        ("harness-failure", "load-error"),
        ("engine-crash", "crash"),
        ("process-launch-error:OSError", "crash"),
        ("termination-failure", "crash"),
        ("desync", "desync"),
    ],
)
def test_fail_fast_reasons_map_to_their_explicit_operational_state(
    reason: str, expected: str
) -> None:
    outcome = classify_outcome(
        parse_log(_valid_lifecycle_prefix(), "run-1", our_slot=1),
        ProcessObservation(exit_code=None, wall_seconds=2, fail_fast_reason=reason),
    )

    assert outcome.state == expected
    assert outcome.failure_reason == reason
