from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Mapping


PINNED_HASHES = {
    "executable": "A6ACF849803F7F38FBAA612B77C910BDE239F6B5A4FF8F8786F719E2AEC0F09D",
    "source_init": "FEB55E924621006C027FD9BF4D94ABE2D9440E43E5FF6D795E6602D9FB6F54E7",
    "lua_archive": "CEBDED703E649DCE0B7CE6B82E8E19843C08DD91EA488B3637E0985B9D51F9CA",
}
GENERATED_MARKER = "-- OVERMIND4 GENERATED INIT v1; DO NOT EDIT;"
INSERTION_ANCHOR = "-- load in .nxt / .nx2 / .scd files that we allow\n"


class InstallationError(RuntimeError):
    """The installed FAF deployment does not match the inspected build."""


class InitGenerationError(RuntimeError):
    """A custom init cannot be safely and narrowly generated."""


@dataclass(frozen=True)
class RuntimeLayout:
    executable: Path
    source_init: Path
    lua_archive: Path
    schook_directory: Path
    fa_path_file: Path | None = None

    @property
    def generated_init(self) -> Path:
        return self.source_init.with_name("init_overmind4.lua")

    @classmethod
    def default(cls, repository: Path) -> "RuntimeLayout":
        faf = Path("C:/ProgramData/FAForever")
        return cls(
            executable=faf / "bin" / "ForgedAlliance.exe",
            source_init=faf / "bin" / "init.lua",
            lua_archive=faf / "gamedata" / "lua.nx2",
            schook_directory=repository / "tools" / "autorun" / "schook",
            fa_path_file=faf / "fa_path.lua",
        )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_installation(
    layout: RuntimeLayout,
    expected_hashes: Mapping[str, str] = PINNED_HASHES,
) -> dict[str, str]:
    paths = {
        "executable": layout.executable,
        "source_init": layout.source_init,
        "lua_archive": layout.lua_archive,
    }
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise InstallationError(
                f"missing {name}: {path}. Reinstall or update the FAF 3836 runner pins."
            )
        actual[name] = _file_hash(path)
        expected = expected_hashes.get(name, "").upper()
        if actual[name] != expected:
            raise InstallationError(
                f"hash changed for {name}: expected {expected}, got {actual[name]} at {path}. "
                "Refuse to launch until the new FAF version is inspected."
            )
    if not layout.schook_directory.is_dir():
        raise InstallationError(f"missing autorun schook directory: {layout.schook_directory}")
    return actual


def _lua_quote(value: str) -> str:
    return (
        "'"
        + value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        + "'"
    )


def read_init_source(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def transform_init(source: str, schook_directory: Path, source_hash: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    anchor = INSERTION_ANCHOR.rstrip("\n") + newline
    count = source.count(anchor)
    if count != 1:
        raise InitGenerationError(
            f"current init must contain the exact insertion anchor exactly once; found {count}"
        )
    mount = newline.join(
        (
            "-- OVERMIND4 AUTORUN MOUNT BEGIN",
            f"MountDirectory({_lua_quote(str(schook_directory.resolve()))}, '/schook')",
            "-- OVERMIND4 AUTORUN MOUNT END",
            "",
        )
    )
    header = f"{GENERATED_MARKER} source_sha256={source_hash.upper()}{newline}"
    return header + source.replace(anchor, mount + anchor, 1)


def install_generated_init(
    layout: RuntimeLayout,
    expected_hashes: Mapping[str, str] = PINNED_HASHES,
) -> Path:
    actual = verify_installation(layout, expected_hashes)
    source = read_init_source(layout.source_init)
    generated = transform_init(source, layout.schook_directory, actual["source_init"])
    target = layout.generated_init
    if target.exists():
        current = target.read_text(encoding="utf-8")
        if not current.startswith(GENERATED_MARKER):
            raise InitGenerationError(
                f"existing generated-init target is not recognized as ours: {target}"
            )
        if current == generated:
            return target

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".init_overmind4-", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(generated)
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return target
