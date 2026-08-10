from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Callable, Mapping

from .installation import (
    PINNED_HASHES,
    RuntimeLayout,
    install_generated_init,
    read_init_source,
    transform_init,
    verify_installation,
)
from .model import FAF_BUILD, FAF_COMMIT, MOD_UID, RunConfig
from .parsing import Outcome, ProcessObservation, classify_outcome, parse_log
from .plan import ArtifactPaths, build_argv
from .process import Monitor, ProcessHandle, spawn_owned
from .reporting import render_json, render_markdown


Spawn = Callable[[list[str], Path], ProcessHandle]
ISOLATED_PREFS = """options_overrides = {
    language = 'us'
}
profile = {
    current = 1,
    profiles = {
        {
            Name = 'Overmind4 Harness',
            options = {
                primary_adapter = 'windowed',
                secondary_adapter = 'disabled',
                selectedlanguage = 'us'
            }
        }
    }
}
version = {
    major = 1
}
active_mods = { }
"""


def _preferences_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required to isolate FAF preferences")
    return (
        Path(local_app_data)
        / "Gas Powered Games"
        / "Supreme Commander Forged Alliance"
    )


def _default_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"om4-{timestamp}-{secrets.token_hex(4)}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _git_commit(repository: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _hash_files(files: list[Path], base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(base).as_posix().lower()):
        relative = path.relative_to(base).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest().upper()


def _content_hash(repository: Path) -> str:
    files: list[Path] = []
    for relative in ("mod_info.lua", "hook", "lua", "tools/autorun"):
        path = repository / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return _hash_files(files, repository)


class MapDiscoveryError(RuntimeError):
    """The pinned FAF path data or requested map cannot be resolved safely."""


_FA_PATH_ASSIGNMENT = re.compile(
    r'^\s*(fa_path|custom_vault_path|GameVersion)\s*=\s*"([^"\r\n]*)"\s*$'
)


def parse_fa_path_assignments(source: str) -> dict[str, str]:
    required = {"fa_path", "custom_vault_path", "GameVersion"}
    values: dict[str, str] = {}
    for line in source.splitlines():
        match = _FA_PATH_ASSIGNMENT.fullmatch(line)
        if not match:
            continue
        name, value = match.groups()
        if name in values:
            raise MapDiscoveryError(f"duplicate {name} assignment in fa_path.lua")
        values[name] = value
    missing = sorted(required - values.keys())
    if missing:
        raise MapDiscoveryError(
            "fa_path.lua is missing required simple assignments: " + ", ".join(missing)
        )
    if values["GameVersion"] != str(FAF_BUILD):
        raise MapDiscoveryError(
            f"fa_path.lua reports game build {values['GameVersion']}; expected {FAF_BUILD}"
        )
    return values


def discover_map_roots(repository: Path, fa_path_file: Path) -> tuple[Path, ...]:
    if not fa_path_file.is_file():
        raise MapDiscoveryError(f"missing pinned FAF path file: {fa_path_file}")
    values = parse_fa_path_assignments(fa_path_file.read_text(encoding="utf-8"))
    candidates = [
        Path(values["fa_path"]) / "maps",
        Path(values["custom_vault_path"]) / "maps",
    ]
    if repository.parent.name.lower() == "mods":
        candidates.append(repository.parent.parent / "maps")
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        identifier = str(candidate).replace("\\", "/").lower()
        if identifier not in seen:
            seen.add(identifier)
            roots.append(candidate)
    return tuple(roots)


def fingerprint_map(map_id: str, roots: tuple[Path, ...]) -> dict[str, object]:
    map_directory = next((root / map_id for root in roots if (root / map_id).is_dir()), None)
    if map_directory is None:
        locations = ", ".join(str(root) for root in roots)
        raise MapDiscoveryError(
            f"map folder for {map_id} was not found in discovered roots: {locations}"
        )
    files = [item for item in map_directory.rglob("*") if item.is_file()]
    scenarios = sorted(
        (item for item in files if item.name.lower().endswith("_scenario.lua")),
        key=lambda item: item.name.lower(),
    )
    if len(scenarios) != 1:
        raise MapDiscoveryError(
            f"map folder {map_directory} must contain exactly one scenario file; "
            f"found {len(scenarios)}"
        )
    match = re.search(
        r"(?m)^\s*version\s*=\s*(\d+)\s*$",
        scenarios[0].read_text("utf-8"),
    )
    if not match:
        raise MapDiscoveryError(f"map scenario does not declare a numeric version: {scenarios[0]}")
    version = int(match.group(1))
    return {"version": version, "sha256": _hash_files(files, map_directory)}


@dataclass(frozen=True)
class RunnerDependencies:
    layout: RuntimeLayout
    preferences_directory: Path
    expected_hashes: Mapping[str, str]
    run_id_factory: Callable[[], str]
    utc_now: Callable[[], str]
    git_commit: Callable[[Path], str | None]
    content_hash: Callable[[Path], str]
    map_fingerprint: Callable[[str], dict[str, object]]
    spawn: Spawn
    monitor: Monitor

    @classmethod
    def default(cls, repository: Path) -> "RunnerDependencies":
        layout = RuntimeLayout.default(repository)
        assert layout.fa_path_file is not None
        map_roots = discover_map_roots(repository, layout.fa_path_file)
        return cls(
            layout=layout,
            preferences_directory=_preferences_directory(),
            expected_hashes=PINNED_HASHES,
            run_id_factory=_default_run_id,
            utc_now=_utc_now,
            git_commit=_git_commit,
            content_hash=_content_hash,
            map_fingerprint=lambda map_id: fingerprint_map(map_id, map_roots),
            spawn=spawn_owned,
            monitor=Monitor(),
        )


@dataclass(frozen=True)
class RunnerResult:
    run_id: str
    dry_run: bool
    paths: ArtifactPaths
    argv: list[str]
    outcome: Outcome | None


def _canonical_json(document: object) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _config_hash(config: RunConfig) -> str:
    encoded = json.dumps(
        config.document(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest().upper()


def _preserve_and_remove_preferences(runtime_path: Path, artifact_path: Path) -> str | None:
    snapshot_failure: str | None = None
    try:
        artifact_path.write_bytes(runtime_path.read_bytes())
    except OSError as error:
        snapshot_failure = f"preferences-snapshot-error:{type(error).__name__}"

    try:
        runtime_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        return f"preferences-cleanup-error:{type(error).__name__}"
    return snapshot_failure


class Runner:
    def __init__(self, repository: Path, dependencies: RunnerDependencies | None = None) -> None:
        self.repository = repository.resolve()
        self.dependencies = dependencies or RunnerDependencies.default(self.repository)

    def run(
        self,
        config: RunConfig,
        output_directory: Path,
        *,
        dry_run: bool,
    ) -> RunnerResult:
        deps = self.dependencies
        hashes = verify_installation(deps.layout, deps.expected_hashes)
        # Validate the exact init transformation even in dry-run, but write nothing.
        transform_init(
            read_init_source(deps.layout.source_init),
            deps.layout.schook_directory,
            hashes["source_init"],
        )
        run_id = deps.run_id_factory()
        if not output_directory.is_absolute():
            output_directory = self.repository / output_directory
        output_directory = output_directory.resolve()
        paths = ArtifactPaths.for_run(output_directory, run_id)
        argv = build_argv(
            deps.layout.executable,
            deps.layout.generated_init,
            config,
            paths,
            run_id,
        )
        map_data = deps.map_fingerprint(config.map_id)
        if dry_run:
            return RunnerResult(run_id, True, paths, argv, None)

        if paths.run_dir.exists():
            raise FileExistsError(f"run directory already exists: {paths.run_dir}")
        preferences_directory = deps.preferences_directory.resolve()
        runtime_prefs_path = (preferences_directory / paths.prefs_filename).resolve()
        if runtime_prefs_path.parent != preferences_directory:
            raise RuntimeError("isolated prefs filename escaped the FAF preferences directory")
        if runtime_prefs_path.exists():
            raise FileExistsError(
                f"isolated prefs file already exists: {runtime_prefs_path}"
            )
        install_generated_init(deps.layout, deps.expected_hashes)
        paths.run_dir.mkdir(parents=True, exist_ok=False)
        with paths.prefs_path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(ISOLATED_PREFS)
        created_at = deps.utc_now()
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": created_at,
            "faf": {
                "build": FAF_BUILD,
                "commit": FAF_COMMIT,
                "executable": str(deps.layout.executable),
                "source_init": str(deps.layout.source_init),
                "generated_init": str(deps.layout.generated_init),
                "lua_archive": str(deps.layout.lua_archive),
                "hashes": hashes,
            },
            "overmind4": {
                "uid": MOD_UID,
                "git_commit": deps.git_commit(self.repository),
                "content_sha256": deps.content_hash(self.repository),
            },
            "config": config.document(),
            "config_sha256": _config_hash(config),
            "map": {"id": config.map_id, **map_data},
            "opponent": {
                "source": "FAF stock",
                "source_commit": FAF_COMMIT,
                "personality": config.opponent_ai,
                "cheats": False,
            },
            "active_sim_mod_uids": [MOD_UID],
            "preferences": {
                "argument": paths.prefs_filename,
                "runtime_path": str(runtime_prefs_path),
                "initial_sha256": hashlib.sha256(
                    ISOLATED_PREFS.encode("utf-8")
                ).hexdigest().upper(),
            },
            "argv": argv,
            "artifacts": {
                "log": str(paths.log_path),
                "replay": str(paths.replay_path),
                "prefs": str(paths.prefs_path),
                "report_json": str(paths.report_json_path),
                "report_markdown": str(paths.report_markdown_path),
            },
        }
        with paths.manifest_path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(_canonical_json(manifest))

        preferences_directory.mkdir(parents=True, exist_ok=True)
        with runtime_prefs_path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(ISOLATED_PREFS)
        preferences_failure: str | None = None
        try:
            try:
                process = deps.spawn(argv, deps.layout.executable.parent)
            except Exception as error:
                observation = ProcessObservation(
                    exit_code=None,
                    wall_seconds=0.0,
                    fail_fast_reason=f"process-launch-error:{type(error).__name__}",
                )
            else:
                try:
                    observation = deps.monitor.wait(
                        process,
                        paths.log_path,
                        config.wall_time_limit,
                        run_id=run_id,
                    )
                except Exception as error:
                    exit_code, cleanup_failed = deps.monitor.stop_owned(process)
                    observation = ProcessObservation(
                        exit_code=exit_code,
                        wall_seconds=0.0,
                        fail_fast_reason=(
                            "termination-failure"
                            if cleanup_failed
                            else f"process-monitor-error:{type(error).__name__}"
                        ),
                    )
                except BaseException:
                    deps.monitor.stop_owned(process)
                    raise
        finally:
            preferences_failure = _preserve_and_remove_preferences(
                runtime_prefs_path, paths.prefs_path
            )

        if preferences_failure:
            observation = ProcessObservation(
                exit_code=observation.exit_code,
                wall_seconds=observation.wall_seconds,
                wall_timeout=observation.wall_timeout,
                fail_fast_reason=preferences_failure,
                sim_timeout=observation.sim_timeout,
            )

        log_text = (
            paths.log_path.read_text(encoding="utf-8", errors="replace")
            if paths.log_path.is_file()
            else ""
        )
        telemetry = parse_log(log_text, run_id, config.our_slot)
        outcome = classify_outcome(telemetry, observation)
        completed_at = deps.utc_now()
        artifacts_present = {
            "log": paths.log_path.is_file(),
            "replay": paths.replay_path.is_file(),
        }
        paths.report_json_path.write_text(
            render_json(
                outcome,
                run_id,
                completed_at=completed_at,
                artifacts_present=artifacts_present,
            ),
            encoding="utf-8",
            newline="",
        )
        paths.report_markdown_path.write_text(
            render_markdown(outcome, run_id), encoding="utf-8", newline=""
        )
        return RunnerResult(run_id, False, paths, argv, outcome)
