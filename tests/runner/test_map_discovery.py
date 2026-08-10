from __future__ import annotations

from pathlib import Path

import pytest

from tools.overmind4_runner.runner import (
    MapDiscoveryError,
    discover_map_roots,
    fingerprint_map,
    parse_fa_path_assignments,
)


def test_fa_path_assignments_are_parsed_as_data_without_executing_lua(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    source = (
        'fa_path = "D:/Games/FA"\n'
        'custom_vault_path = "E:/Portable/My Games/FAF"\n'
        'GameVersion = "3836"\n'
        f'os.execute("touch {marker}")\n'
    )

    values = parse_fa_path_assignments(source)

    assert values == {
        "fa_path": "D:/Games/FA",
        "custom_vault_path": "E:/Portable/My Games/FAF",
        "GameVersion": "3836",
    }
    assert not marker.exists()


@pytest.mark.parametrize(
    "source",
    [
        'fa_path = "D:/FA"\nGameVersion = "3836"\n',
        (
            'fa_path = "D:/FA"\nfa_path = "E:/Other"\n'
            'custom_vault_path = "E:/Vault"\nGameVersion = "3836"\n'
        ),
        (
            'fa_path = "D:/FA"\ncustom_vault_path = "E:/Vault"\n'
            'GameVersion = "9999"\n'
        ),
    ],
)
def test_fa_path_parser_fails_closed_on_missing_duplicate_or_wrong_build(source: str) -> None:
    with pytest.raises(MapDiscoveryError):
        parse_fa_path_assignments(source)


def test_map_roots_use_current_fa_path_and_repository_vault_without_username_literals(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "Portable Vault" / "mods" / "Overmind4"
    repository.mkdir(parents=True)
    fa_file = tmp_path / "ProgramData" / "FAForever" / "fa_path.lua"
    fa_file.parent.mkdir(parents=True)
    fa_file.write_text(
        'fa_path = "D:/Games/Current FA"\n'
        'custom_vault_path = "E:/Current Vault"\n'
        'GameVersion = "3836"\n',
        encoding="utf-8",
    )

    roots = discover_map_roots(repository, fa_file)

    assert roots == (
        Path("D:/Games/Current FA/maps"),
        Path("E:/Current Vault/maps"),
        repository.parent.parent / "maps",
    )
    assert all("DEV - PCOM" not in str(root) for root in roots[:2])


def test_versioned_map_fingerprint_is_portable_deterministic_and_content_sensitive(
    tmp_path: Path,
) -> None:
    root = tmp_path / "relocatable" / "maps"
    map_id = "adaptive_moon.v0004"
    directory = root / map_id
    directory.mkdir(parents=True)
    # FAF versioned-map folders keep the version in the directory name while
    # the scenario filename commonly retains the unversioned map name.
    scenario = directory / "adaptive_moon_scenario.lua"
    scenario.write_text("version = 4\nScenarioInfo = {}\n", encoding="utf-8")
    (directory / f"{map_id}.scmap").write_bytes(b"map-v1")

    first = fingerprint_map(map_id, (root,))
    second = fingerprint_map(map_id, (root,))
    (directory / f"{map_id}.scmap").write_bytes(b"map-v2")
    changed = fingerprint_map(map_id, (root,))

    assert first == second
    assert first["version"] == 4
    assert first["sha256"] != changed["sha256"]


def test_map_fingerprint_fails_when_no_discovered_root_contains_the_map(tmp_path: Path) -> None:
    with pytest.raises(MapDiscoveryError, match="not found"):
        fingerprint_map("SCMP_007", (tmp_path / "maps",))
