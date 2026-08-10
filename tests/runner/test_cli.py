from __future__ import annotations

from pathlib import Path

import pytest

from tools.overmind4_runner.cli import exit_code_for_state, parse_cli


ROOT = Path(__file__).resolve().parents[2]


def test_cli_defaults_match_daily_one_game_workflow() -> None:
    options = parse_cli([])

    assert options.config.map_id == "SCMP_007"
    assert options.config.speed == 25
    assert options.config.ai_specs[0].key == "overmind4"
    assert options.config.ai_specs[1].key == "easy"
    assert options.dry_run is False
    assert options.output_dir == Path("artifacts/runs")


def test_cli_accepts_all_supported_match_controls() -> None:
    options = parse_cli(
        [
            "--map", "SCMP_012",
            "--seed", "42",
            "--speed", "30",
            "--sim-time", "900",
            "--wall-time", "120",
            "--unit-cap", "750",
            "--our-ai", "overmind4_test",
            "--opponent-ai", "rush",
            "--our-faction", "2",
            "--opponent-faction", "3",
            "--our-slot", "2",
            "--opponent-slot", "1",
            "--our-team", "4",
            "--opponent-team", "5",
            "--output-dir", "C:/out with spaces",
            "--dry-run",
        ]
    )

    assert options.config.map_id == "SCMP_012"
    assert options.config.seed == 42
    assert options.config.speed == 30
    assert options.config.sim_time_limit == 900
    assert options.config.wall_time_limit == 120
    assert options.config.unit_cap == 750
    assert options.config.ai_specs[0].wire == "2:overmind4_test:2:4"
    assert options.config.ai_specs[1].wire == "1:rush:3:5"
    assert options.output_dir == Path("C:/out with spaces")
    assert options.dry_run is True


def test_cli_reports_invalid_values_without_constructing_a_run() -> None:
    with pytest.raises(SystemExit):
        parse_cli(["--our-ai", "../../unsafe"])


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("win", 0),
        ("loss", 0),
        ("draw", 0),
        ("sim-timeout", 1),
        ("wall-timeout", 1),
        ("crash", 1),
        ("load-error", 1),
        ("desync", 1),
        ("missing-result", 1),
    ],
)
def test_cli_is_nonzero_for_timeouts_and_operational_non_results(
    state: str, expected: int
) -> None:
    assert exit_code_for_state(state) == expected


def test_powershell_entry_point_forwards_each_control_without_expression_evaluation() -> None:
    entry = ROOT / "tools" / "run-one.ps1"
    source = entry.read_text(encoding="utf-8")

    assert "Invoke-Expression" not in source
    assert "--map" in source
    assert "--seed" in source
    assert "--speed" in source
    assert "--sim-time" in source
    assert "--wall-time" in source
    assert "--unit-cap" in source
    assert "--our-ai" in source
    assert "--opponent-ai" in source
    assert "--our-faction" in source
    assert "--opponent-faction" in source
    assert "--our-slot" in source
    assert "--opponent-slot" in source
    assert "--output-dir" in source
    assert "@pythonArguments" in source


def test_runner_artifacts_are_ignored_and_provenance_is_recorded() -> None:
    assert "artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    provenance = (ROOT / "tools" / "autorun" / "PROVENANCE.md").read_text(
        encoding="utf-8"
    )
    assert "development-tools" in provenance
    assert "FAF-AI-Autorun" in provenance
    assert "fresh implementation" in provenance
