from __future__ import annotations

from pathlib import Path

import pytest

from tools.overmind4_runner.model import AISpec, RunConfig, ValidationError
from tools.overmind4_runner.plan import ArtifactPaths, build_argv


def test_defaults_describe_one_fixed_overmind4_vs_easy_match() -> None:
    config = RunConfig()

    assert config.map_id == "SCMP_007"
    assert config.seed == 7777
    assert config.speed == 25
    assert config.sim_time_limit == 1800
    assert config.wall_time_limit == 300
    assert config.ai_specs == (
        AISpec(slot=1, key="overmind4", faction=1, team=1),
        AISpec(slot=2, key="easy", faction=1, team=2),
    )


def test_versioned_map_identifier_is_allowed_without_allowing_path_traversal() -> None:
    assert RunConfig(map_id="adaptive_moon.v0004").map_id == "adaptive_moon.v0004"

    with pytest.raises(ValidationError):
        RunConfig(map_id="adaptive_moon..v0004")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("map_id", "../SCMP_007"),
        ("seed", -1),
        ("seed", 2_147_483_648),
        ("speed", 0),
        ("speed", 101),
        ("sim_time_limit", 0),
        ("wall_time_limit", 0),
        ("our_slot", 0),
        ("our_slot", 17),
        ("opponent_slot", 17),
        ("our_faction", 0),
        ("opponent_faction", 5),
        ("our_team", 0),
        ("opponent_team", 17),
        ("our_ai", "../../evil"),
        ("opponent_ai", "easy:bad"),
    ],
)
def test_invalid_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RunConfig(**{field: value})


def test_duplicate_slots_and_same_team_are_rejected() -> None:
    with pytest.raises(ValidationError, match="distinct slots"):
        RunConfig(our_slot=2, opponent_slot=2)

    with pytest.raises(ValidationError, match="opposing teams"):
        RunConfig(our_team=1, opponent_team=1)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1:easy:1",
        "1:easy:1:1:extra",
        "x:easy:1:1",
        "0:easy:1:1",
        "17:easy:1:1",
        "1:../easy:1:1",
        "1:easy:0:1",
        "1:easy:5:1",
        "1:easy:1:0",
        "1:easy:1:17",
    ],
)
def test_ai_spec_parser_rejects_malformed_or_unsafe_values(text: str) -> None:
    with pytest.raises(ValidationError):
        AISpec.parse(text)


def test_ai_spec_has_canonical_wire_format() -> None:
    assert AISpec.parse("2:easy:1:2").wire == "2:easy:1:2"


def test_artifact_paths_are_explicit_and_unique() -> None:
    first = ArtifactPaths.for_run(Path("C:/work output"), "run-0001")
    second = ArtifactPaths.for_run(Path("C:/work output"), "run-0002")

    assert first.run_dir != second.run_dir
    assert first.log_path == first.run_dir / "game.log"
    assert first.replay_path == first.run_dir / "game.scfareplay"
    assert first.manifest_path == first.run_dir / "manifest.json"
    assert first.report_json_path == first.run_dir / "report.json"
    assert first.report_markdown_path == first.run_dir / "report.md"


def test_artifact_paths_reject_unsafe_run_ids() -> None:
    with pytest.raises(ValidationError):
        ArtifactPaths.for_run(Path("artifacts"), "../escape")


def test_exact_argv_preserves_paths_with_spaces_as_individual_arguments() -> None:
    artifacts = ArtifactPaths.for_run(Path("C:/reports with spaces"), "run-0001")
    executable = Path("C:/Program Files/FAF/ForgedAlliance.exe")
    generated_init = Path("C:/Program Files/FAF/init_overmind4.lua")

    argv = build_argv(executable, generated_init, RunConfig(), artifacts, "run-0001")

    assert argv[0] == str(executable)
    assert argv[argv.index("/init") + 1] == str(generated_init)
    assert argv[argv.index("/log") + 1] == str(artifacts.log_path)
    assert argv[argv.index("/savereplay") + 1] == str(artifacts.replay_path)
    assert argv[argv.index("/aitest") + 1] == "1:overmind4:1:1,2:easy:1:2"
    assert argv[argv.index("/map") + 1] == "SCMP_007"
    assert argv[argv.index("/seed") + 1] == "7777"
    assert argv[argv.index("/speed") + 1] == "25"
    assert argv[argv.index("/maxtime") + 1] == "1800"
    assert argv[argv.index("/om4runid") + 1] == "run-0001"
    assert "/nobugreport" in argv
    assert "/nosound" in argv
    assert "/exitongameover" in argv
    assert all('"' not in item for item in argv)
