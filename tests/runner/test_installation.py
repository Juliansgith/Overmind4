from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.overmind4_runner.installation import (
    GENERATED_MARKER,
    InitGenerationError,
    InstallationError,
    RuntimeLayout,
    install_generated_init,
    transform_init,
    verify_installation,
)


ANCHOR = "-- load in .nxt / .nx2 / .scd files that we allow\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _layout(tmp_path: Path) -> tuple[RuntimeLayout, dict[str, str]]:
    exe = tmp_path / "bin" / "ForgedAlliance.exe"
    init = tmp_path / "bin" / "init.lua"
    archive = tmp_path / "gamedata" / "lua.nx2"
    schook = tmp_path / "repo with ' quote" / "tools" / "autorun" / "schook"
    exe.parent.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    schook.mkdir(parents=True)
    exe.write_bytes(b"exe")
    init.write_text("prefix\n" + ANCHOR + "suffix\n", encoding="utf-8")
    archive.write_bytes(b"lua")
    layout = RuntimeLayout(exe, init, archive, schook)
    expected = {
        "executable": _sha(b"exe"),
        "source_init": _sha(init.read_bytes()),
        "lua_archive": _sha(b"lua"),
    }
    return layout, expected


def test_verify_installation_returns_actual_pinned_hashes(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)

    assert verify_installation(layout, expected) == expected


def test_verify_installation_fails_closed_when_a_file_is_missing(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)
    layout.lua_archive.unlink()

    with pytest.raises(InstallationError, match="missing lua_archive"):
        verify_installation(layout, expected)


def test_verify_installation_fails_closed_when_any_hash_changes(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)
    layout.executable.write_bytes(b"updated executable")

    with pytest.raises(InstallationError, match="hash changed.*executable"):
        verify_installation(layout, expected)


def test_transform_init_inserts_one_physical_schook_mount_at_exact_anchor(tmp_path: Path) -> None:
    source = "prefix\n" + ANCHOR + "suffix\n"
    schook = tmp_path / "folder with spaces" / "schook"

    generated = transform_init(source, schook, "A" * 64)

    assert generated.startswith(f"{GENERATED_MARKER} source_sha256={'A' * 64}\n")
    assert generated.count("MountDirectory(") == 1
    assert "'/schook'" in generated
    assert str(schook).replace("\\", "\\\\") in generated
    assert generated.index("MountDirectory(") < generated.index(ANCHOR.strip())


def test_transform_init_escapes_quotes_newlines_and_backslashes() -> None:
    source = "prefix\n" + ANCHOR + "suffix\n"
    path = Path("C:/odd ' path/back\\slash")

    generated = transform_init(source, path, "B" * 64)

    assert "odd \\' path" in generated
    assert "back\\\\slash" in generated
    assert generated.count("\n") == source.count("\n") + 4


def test_transform_init_preserves_the_pinned_source_crlf_line_endings() -> None:
    source = (
        "prefix\r\n"
        "-- load in .nxt / .nx2 / .scd files that we allow\r\n"
        "suffix\r\n"
    )

    generated = transform_init(source, Path("C:/schook"), "D" * 64)

    assert generated.count("\r\n") == source.count("\r\n") + 4
    assert "\n" not in generated.replace("\r\n", "")


@pytest.mark.parametrize(
    "source",
    [
        "no compatible insertion point\n",
        ANCHOR + "middle\n" + ANCHOR,
    ],
)
def test_transform_init_refuses_missing_or_ambiguous_anchor(source: str) -> None:
    with pytest.raises(InitGenerationError, match="exactly once"):
        transform_init(source, Path("C:/schook"), "C" * 64)


def test_install_refuses_to_overwrite_an_unrecognized_target(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)
    layout.generated_init.write_text("user owned", encoding="utf-8")

    with pytest.raises(InitGenerationError, match="not recognized"):
        install_generated_init(layout, expected)

    assert layout.generated_init.read_text(encoding="utf-8") == "user owned"


def test_install_is_deterministic_idempotent_and_regenerates_our_marker(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)

    first = install_generated_init(layout, expected)
    first_bytes = first.read_bytes()
    second = install_generated_init(layout, expected)
    assert second.read_bytes() == first_bytes

    second.write_text(GENERATED_MARKER + " stale\n", encoding="utf-8")
    regenerated = install_generated_init(layout, expected)
    assert regenerated.read_bytes() == first_bytes


def test_install_never_modifies_the_pinned_source_init(tmp_path: Path) -> None:
    layout, expected = _layout(tmp_path)
    before = layout.source_init.read_bytes()

    install_generated_init(layout, expected)

    assert layout.source_init.read_bytes() == before
