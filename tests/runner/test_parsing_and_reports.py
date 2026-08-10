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


def _terminal_line(result: str, *, army: int = 1) -> str:
    return (
        "info: OM4|v=1|kind=lifecycle|army="
        f"{army}|event=terminal|result={result}\n"
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


def test_corroborated_win_outranks_late_engine_error_and_reports_it_as_warning() -> None:
    text = (
        _valid_lifecycle_prefix()
        + _result_line("defeat -10", army=2, sim=642)
        + (
            "warning: Error running lua script: "
            "...lua.nx2\\lua\\platoon.lua(1528): attempt to call method "
            "`GetLocationCoords' (a nil value)\n"
        )
        + _terminal_line("victory")
        + _result_line("victory 10", sim=647)
        + 'debug: GpgNetSend JsonStats {"stats":[]}\n'
    )
    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(
            exit_code=1,
            wall_seconds=34.7,
            fail_fast_reason="lua-error",
        ),
    )

    assert outcome.state == "win"
    assert outcome.is_win is True
    assert outcome.failure_reason is None
    assert outcome.warnings == ("lua-error",)

    document = json.loads(render_json(outcome, run_id="run-1"))
    assert document["warnings"] == ["lua-error"]
    assert "- Warnings: lua-error" in render_markdown(outcome, run_id="run-1")


@pytest.mark.parametrize(
    "startup_with_error",
    [
        "warning: LUA ERROR: import failed\n" + _valid_lifecycle_prefix(),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1|map=SCMP_007\n"
            "warning: LUA ERROR: import failed\n"
            "OM4|v=1|kind=lifecycle|army=1|event=created|plan=none\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1|map=SCMP_007\n"
            "OM4|v=1|kind=lifecycle|army=1|event=created|plan=none\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "warning: LUA ERROR: startup failed\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
        ),
    ],
)
def test_engine_error_before_completed_startup_lifecycle_remains_a_load_error(
    startup_with_error: str,
) -> None:
    text = (
        startup_with_error
        + _terminal_line("victory")
        + _result_line("victory 10")
    )

    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(exit_code=1, wall_seconds=4, fail_fast_reason="lua-error"),
    )

    assert outcome.state == "load-error"
    assert outcome.is_win is False
    assert outcome.failure_reason == "lua-error"
    assert outcome.warnings == ()


def test_engine_error_without_matching_brain_terminal_remains_a_load_error() -> None:
    text = (
        _valid_lifecycle_prefix()
        + "warning: LUA ERROR: update failed\n"
        + _result_line("victory 10")
    )

    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(exit_code=1, wall_seconds=4, fail_fast_reason="lua-error"),
    )

    assert outcome.state == "load-error"
    assert outcome.failure_reason == "lua-error"
    assert outcome.warnings == ()


def test_owned_harness_failure_is_never_downgraded_by_same_named_engine_warning() -> None:
    text = (
        _valid_lifecycle_prefix()
        + "warning: LUA ERROR: late stock callback failed\n"
        + "OM4HARNESS|v=1|kind=failure|run=run-1|reason=lua-error\n"
        + _terminal_line("victory")
        + _result_line("victory 10")
    )

    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(exit_code=1, wall_seconds=4, fail_fast_reason="lua-error"),
    )

    assert outcome.state == "load-error"
    assert outcome.is_win is False
    assert outcome.failure_reason == "lua-error"
    assert outcome.warnings == ()


def test_terminal_before_started_brain_lifecycle_cannot_corroborate_an_engine_error() -> None:
    text = (
        "OM4HARNESS|v=1|kind=start|run=run-1|map=SCMP_007\n"
        + _terminal_line("victory")
        + "OM4|v=1|kind=lifecycle|army=1|event=created|plan=none\n"
        + "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
        + "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
        + "warning: LUA ERROR: late update failed\n"
        + _result_line("victory 10")
    )

    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(exit_code=1, wall_seconds=4, fail_fast_reason="lua-error"),
    )

    assert outcome.state == "load-error"
    assert outcome.is_win is False
    assert outcome.failure_reason == "lua-error"
    assert outcome.lifecycle.reason == "lifecycle-out-of-order"


@pytest.mark.parametrize(
    ("completion_lines", "expected_reason"),
    [
        (
            _terminal_line("defeat") + _result_line("victory 10"),
            "terminal-result-mismatch",
        ),
        (
            _terminal_line("victory")
            + _result_line("victory 10")
            + _result_line("victory 10", sim=124),
            "duplicate-official-result",
        ),
        (
            _terminal_line("victory")
            + _terminal_line("victory")
            + _result_line("victory 10"),
            "duplicate-brain-terminal",
        ),
        (
            _terminal_line("victory")
            + _result_line("victory 10")
            + _result_line("defeat -10", sim=124),
            "conflicting-official-results",
        ),
    ],
)
def test_mismatched_duplicate_or_conflicting_results_fail_closed(
    completion_lines: str,
    expected_reason: str,
) -> None:
    outcome = classify_outcome(
        parse_log(_valid_lifecycle_prefix() + completion_lines, "run-1", our_slot=1),
        ProcessObservation(exit_code=0, wall_seconds=4),
    )

    assert outcome.state == "malformed"
    assert outcome.is_win is False
    assert outcome.failure_reason == expected_reason


@pytest.mark.parametrize(
    "safety_reason",
    [
        "termination-failure",
        "preferences-cleanup-error:PermissionError",
        "preferences-snapshot-error:PermissionError",
    ],
)
def test_safety_failure_outranks_a_corroborated_official_win(safety_reason: str) -> None:
    text = (
        _valid_lifecycle_prefix()
        + "warning: LUA ERROR: late stock callback failed\n"
        + _terminal_line("victory")
        + _result_line("victory 10")
    )

    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(
            exit_code=1,
            wall_seconds=4,
            fail_fast_reason=safety_reason,
        ),
    )

    assert outcome.state == "crash"
    assert outcome.is_win is False
    assert outcome.failure_reason == safety_reason
    assert outcome.warnings == ()


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


def test_structured_sim_timeout_cannot_be_overridden_by_generic_wall_timeout() -> None:
    telemetry = parse_log(
        _valid_lifecycle_prefix()
        + "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n",
        "run-1",
        our_slot=1,
    )

    outcome = classify_outcome(
        telemetry,
        ProcessObservation(
            exit_code=-1,
            wall_seconds=300,
            wall_timeout=True,
            sim_timeout=True,
        ),
    )

    assert outcome.state == "sim-timeout"
    assert outcome.failure_reason is None


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (
            "OM4|v=1|kind=lifecycle|army=1|event=created\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n",
            "missing-harness-start",
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n",
            "fallback-brain",
        ),
        (
            "OM4HARNESS|v=1|kind=start|run=run-1\n"
            "OM4|v=1|kind=lifecycle|army=1|event=begin_session\n"
            "OM4|v=1|kind=lifecycle|army=1|event=created\n"
            "OM4HARNESS|v=1|kind=speed|run=run-1|requested=25|sim=1\n"
            "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n",
            "lifecycle-out-of-order",
        ),
    ],
)
def test_structured_sim_timeout_requires_a_valid_ordered_lifecycle(
    text: str,
    reason: str,
) -> None:
    outcome = classify_outcome(
        parse_log(text, "run-1", our_slot=1),
        ProcessObservation(
            exit_code=-1,
            wall_seconds=300,
            wall_timeout=True,
            sim_timeout=True,
        ),
    )

    assert outcome.state == "load-error"
    assert outcome.failure_reason == reason


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
        (
            "warning: Error running lua script: /lua/example.lua(12): failure\n",
            1,
            "load-error",
        ),
        (
            "warning: Error running OnFrame script in CScriptObject at 1e9a82c0: "
            "...ata\\faforever\\gamedata\\lua.nx2\\lua\\ui\\game\\score.lua(529): "
            "attempt to concatenate field `?' (a nil value)\n",
            1,
            "load-error",
        ),
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


@pytest.mark.parametrize(
    "text",
    [
        "info: unit description says desync resistant\n",
        "debug: documentation example: LUA ERROR: example only\n",
        "info: tooltip text says unable to load map when missing\n",
        "warning: prior report mentioned EXCEPTION_ACCESS_VIOLATION but recovered\n",
        (
            "warning: release notes mention Error running OnFrame script in "
            "CScriptObject at 1e9a82c0 but no error occurred\n"
        ),
    ],
)
def test_log_parser_ignores_benign_unanchored_diagnostic_words(text: str) -> None:
    telemetry = parse_log(text, "run-1", our_slot=1)

    assert telemetry.failure_reason is None


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


@pytest.mark.parametrize(
    ("engine_line", "cleanup_reason"),
    [
        ("warning: LUA ERROR: import failed\n", "termination-failure"),
        (
            "info: DESYNC detected\n",
            "preferences-cleanup-error:PermissionError",
        ),
    ],
)
def test_safety_cleanup_failure_takes_precedence_over_engine_telemetry(
    engine_line: str,
    cleanup_reason: str,
) -> None:
    outcome = classify_outcome(
        parse_log(engine_line, "run-1", our_slot=1),
        ProcessObservation(
            exit_code=None,
            wall_seconds=2,
            fail_fast_reason=cleanup_reason,
        ),
    )

    assert outcome.state == "crash"
    assert outcome.failure_reason == cleanup_reason


@pytest.mark.parametrize(
    ("engine_line", "process_reason", "expected_reason", "expected_state"),
    [
        (
            "warning: LUA ERROR: import failed\n",
            "process-monitor-error:PermissionError",
            "lua-error",
            "load-error",
        ),
        (
            "info: DESYNC detected\n",
            "process-launch-error:OSError",
            "desync",
            "desync",
        ),
    ],
)
def test_genuine_engine_failure_precedes_non_cleanup_process_diagnostics(
    engine_line: str,
    process_reason: str,
    expected_reason: str,
    expected_state: str,
) -> None:
    outcome = classify_outcome(
        parse_log(engine_line, "run-1", our_slot=1),
        ProcessObservation(
            exit_code=None,
            wall_seconds=2,
            fail_fast_reason=process_reason,
        ),
    )

    assert outcome.state == expected_state
    assert outcome.failure_reason == expected_reason
