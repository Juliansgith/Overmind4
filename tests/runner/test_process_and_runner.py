from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from tools.overmind4_runner.installation import RuntimeLayout
from tools.overmind4_runner.model import RunConfig
from tools.overmind4_runner.process import Monitor, detect_fail_fast, terminate_owned_tree
from tools.overmind4_runner.runner import MapDiscoveryError, Runner, RunnerDependencies


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class FakeProcess:
    def __init__(self, poll_values: list[int | None], pid: int = 4242) -> None:
        self.pid = pid
        self.poll_values = iter(poll_values)
        self.last: int | None = None
        self.waited = False

    def poll(self) -> int | None:
        try:
            self.last = next(self.poll_values)
        except StopIteration:
            pass
        return self.last

    def wait(self, timeout: float | None = None) -> int | None:
        self.waited = True
        return self.last


class StuckProcess(FakeProcess):
    def wait(self, timeout: float | None = None) -> int | None:
        self.waited = True
        raise subprocess.TimeoutExpired("ForgedAlliance.exe", timeout)


class BrokenCleanupProcess(FakeProcess):
    def wait(self, timeout: float | None = None) -> int | None:
        raise RuntimeError("cleanup adapter failed")


class FakeTail:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = iter(chunks)

    def read_new(self) -> str:
        return next(self.chunks, "")


class RaisingTail:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def read_new(self) -> str:
        raise self.error


@pytest.mark.parametrize(
    "line",
    [
        "info: unit description says desync resistant\n",
        "debug: documentation example: LUA ERROR: example only\n",
        "info: tooltip text says unable to load map when missing\n",
        "warning: prior report mentioned EXCEPTION_ACCESS_VIOLATION but recovered\n",
    ],
)
def test_fail_fast_ignores_benign_unanchored_diagnostic_words(line: str) -> None:
    assert detect_fail_fast(line, run_id="run-1") is None


def test_fail_fast_accepts_only_run_associated_structured_harness_failure() -> None:
    unrelated = (
        "OM4HARNESS|v=1|kind=failure|run=other-run|reason=mod_unavailable\n"
    )
    associated = (
        "info: OM4HARNESS|v=1|kind=failure|run=run-1|reason=mod_unavailable\n"
    )

    assert detect_fail_fast(unrelated, run_id="run-1") is None
    assert detect_fail_fast(associated, run_id="run-1") == "mod_unavailable"


def test_fail_fast_recognizes_actual_anchored_faf_lua_error_format() -> None:
    line = "warning: Error running lua script: /lua/example.lua(12): failure\n"

    assert detect_fail_fast(line, run_id="run-1") == "lua-error"


def test_monitor_terminates_only_the_spawned_pid_tree_on_wall_timeout(tmp_path: Path) -> None:
    clock = FakeClock()
    process = FakeProcess([None] * 20, pid=4242)
    terminated: list[int] = []
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail([]),
        terminate_tree=lambda pid: terminated.append(pid),
        poll_interval=1,
    )

    observation = monitor.wait(process, tmp_path / "owned.log", wall_timeout=3)

    assert observation.wall_timeout is True
    assert terminated == [4242]
    assert process.waited is True


def test_monitor_contains_timeout_expired_after_owned_tree_termination(tmp_path: Path) -> None:
    clock = FakeClock()
    process = StuckProcess([None] * 10, pid=6262)
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail([]),
        terminate_tree=lambda _: None,
        poll_interval=1,
    )

    observation = monitor.wait(process, tmp_path / "owned.log", wall_timeout=2)

    assert observation.fail_fast_reason == "termination-failure"
    assert observation.wall_timeout is True


def test_monitor_contains_any_cleanup_adapter_failure_and_still_returns_observation(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    process = BrokenCleanupProcess([None] * 10, pid=6363)
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail([]),
        terminate_tree=lambda _: (_ for _ in ()).throw(OSError("taskkill failed")),
        poll_interval=1,
    )

    observation = monitor.wait(process, tmp_path / "owned.log", wall_timeout=2)

    assert observation.fail_fast_reason == "termination-failure"


def test_monitor_stops_on_matching_structured_sim_timeout_without_waiting_for_wall_cap(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    process = FakeProcess([None] * 10, pid=6464)
    terminated: list[int] = []
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail(
            [
                "OM4HARNESS|v=1|kind=timeout|run=unrelated|sim=1800\n",
                "OM4HARNESS|v=1|kind=timeout|run=run-1|sim=1800\n",
            ]
        ),
        terminate_tree=lambda pid: terminated.append(pid),
        poll_interval=1,
    )

    observation = monitor.wait(
        process,
        tmp_path / "owned.log",
        wall_timeout=100,
        run_id="run-1",
    )

    assert observation.sim_timeout is True
    assert observation.wall_timeout is False
    assert observation.fail_fast_reason is None
    assert terminated == [6464]
    assert observation.wall_seconds < 100


def test_monitor_recognizes_a_structured_timeout_split_across_tail_reads(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    process = FakeProcess([None] * 10, pid=6474)
    terminated: list[int] = []
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail(
            [
                "info: OM4HARNESS|v=1|kind=time",
                "out|run=run-1|sim=1800\n",
            ]
        ),
        terminate_tree=lambda pid: terminated.append(pid),
        poll_interval=1,
    )

    observation = monitor.wait(
        process,
        tmp_path / "owned.log",
        wall_timeout=100,
        run_id="run-1",
    )

    assert observation.sim_timeout is True
    assert terminated == [6474]


def test_monitor_fails_fast_on_harness_or_lua_failure_without_touching_other_pids(tmp_path: Path) -> None:
    clock = FakeClock()
    process = FakeProcess([None, None], pid=5151)
    terminated: list[int] = []
    monitor = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=lambda _: FakeTail(["normal\n", "LUA ERROR: bad import\n"]),
        terminate_tree=lambda pid: terminated.append(pid),
        poll_interval=1,
    )

    observation = monitor.wait(process, tmp_path / "owned.log", wall_timeout=100)

    assert observation.fail_fast_reason == "lua-error"
    assert terminated == [5151]


def test_monitor_does_not_read_or_associate_an_unrelated_log(tmp_path: Path) -> None:
    owned = tmp_path / "owned.log"
    unrelated = tmp_path / "newer-unrelated.log"
    unrelated.write_text("LUA ERROR: should never be read", encoding="utf-8")
    seen_paths: list[Path] = []
    clock = FakeClock()
    process = FakeProcess([0])

    def tail_factory(path: Path) -> FakeTail:
        seen_paths.append(path)
        return FakeTail([""])

    observation = Monitor(
        now=clock.now,
        sleep=clock.sleep,
        tail_factory=tail_factory,
        terminate_tree=lambda _: pytest.fail("must not terminate"),
    ).wait(process, owned, wall_timeout=10)

    assert observation.exit_code == 0
    assert seen_paths == [owned]


def test_windows_tree_termination_uses_taskkill_for_exact_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> None:
        calls.append(argv)

    monkeypatch.setattr("tools.overmind4_runner.process.os.name", "nt")
    monkeypatch.setattr("tools.overmind4_runner.process.subprocess.run", fake_run)

    terminate_owned_tree(9090)

    assert calls == [["taskkill", "/PID", "9090", "/T", "/F"]]


@dataclass
class SpawnRecorder:
    process: FakeProcess
    calls: list[tuple[list[str], Path]]

    def __call__(self, argv: list[str], cwd: Path) -> FakeProcess:
        self.calls.append((argv, cwd))
        return self.process


def _deps(tmp_path: Path) -> tuple[RunnerDependencies, RuntimeLayout, dict[str, str], SpawnRecorder]:
    import hashlib

    exe = tmp_path / "faf bin" / "ForgedAlliance.exe"
    init = tmp_path / "faf bin" / "init.lua"
    archive = tmp_path / "gamedata" / "lua.nx2"
    schook = tmp_path / "repo" / "tools" / "autorun" / "schook"
    exe.parent.mkdir(parents=True)
    archive.parent.mkdir(parents=True)
    schook.mkdir(parents=True)
    exe.write_bytes(b"exe")
    init.write_text(
        "prefix\n-- load in .nxt / .nx2 / .scd files that we allow\nsuffix\n",
        encoding="utf-8",
    )
    archive.write_bytes(b"lua")
    layout = RuntimeLayout(exe, init, archive, schook)
    expected = {
        "executable": hashlib.sha256(b"exe").hexdigest().upper(),
        "source_init": hashlib.sha256(init.read_bytes()).hexdigest().upper(),
        "lua_archive": hashlib.sha256(b"lua").hexdigest().upper(),
    }
    spawn = SpawnRecorder(FakeProcess([0]), [])
    deps = RunnerDependencies(
        layout=layout,
        preferences_directory=tmp_path / "local prefs",
        expected_hashes=expected,
        run_id_factory=lambda: "run-fixed",
        utc_now=lambda: "2026-08-10T12:00:00Z",
        git_commit=lambda _: "abc123",
        content_hash=lambda _: "content123",
        map_fingerprint=lambda _: {"version": 3, "sha256": "map123"},
        spawn=spawn,
        monitor=Monitor(
            now=lambda: 10.0,
            sleep=lambda _: None,
            tail_factory=lambda _: FakeTail([]),
            terminate_tree=lambda _: None,
        ),
    )
    return deps, layout, expected, spawn


def test_dry_run_performs_zero_writes_and_zero_process_launches(tmp_path: Path) -> None:
    deps, layout, _, spawn = _deps(tmp_path)
    output = tmp_path / "artifacts"
    source_before = layout.source_init.read_bytes()

    result = Runner(tmp_path / "repo", deps).run(RunConfig(), output, dry_run=True)

    assert result.dry_run is True
    assert not output.exists()
    assert not layout.generated_init.exists()
    assert not deps.preferences_directory.exists()
    assert layout.source_init.read_bytes() == source_before
    assert spawn.calls == []


def test_dry_run_validates_the_requested_map_before_returning_without_writes(
    tmp_path: Path,
) -> None:
    deps, layout, _, spawn = _deps(tmp_path)
    output = tmp_path / "artifacts"

    def missing_map(_: str) -> dict[str, object]:
        raise MapDiscoveryError("requested map is missing")

    deps = replace(deps, map_fingerprint=missing_map)

    with pytest.raises(MapDiscoveryError, match="requested map is missing"):
        Runner(tmp_path / "repo", deps).run(RunConfig(), output, dry_run=True)

    assert not output.exists()
    assert not layout.generated_init.exists()
    assert spawn.calls == []


@pytest.mark.parametrize("error_type", [PermissionError, OSError, RuntimeError])
def test_runner_cleans_exact_spawned_tree_and_reports_every_post_spawn_monitor_error(
    tmp_path: Path,
    error_type: type[Exception],
) -> None:
    deps, layout, _, _ = _deps(tmp_path)
    process = FakeProcess([None] * 10, pid=6565)
    spawn = SpawnRecorder(process, [])
    terminated: list[int] = []
    monitor = Monitor(
        now=lambda: 10.0,
        sleep=lambda _: None,
        tail_factory=lambda _: RaisingTail(error_type("owned log read failed")),
        terminate_tree=lambda pid: terminated.append(pid),
    )
    deps = replace(deps, spawn=spawn, monitor=monitor)

    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(), tmp_path / "artifacts", dry_run=False
    )

    assert terminated == [6565]
    assert process.waited is True
    assert result.outcome is not None
    assert result.outcome.state == "crash"
    assert result.outcome.failure_reason == f"process-monitor-error:{error_type.__name__}"
    assert result.paths.report_json_path.is_file()


def test_runner_contains_cleanup_failures_after_post_spawn_exception_and_reports_crash(
    tmp_path: Path,
) -> None:
    deps, _, _, _ = _deps(tmp_path)
    process = BrokenCleanupProcess([None] * 10, pid=6666)
    spawn = SpawnRecorder(process, [])
    monitor = Monitor(
        now=lambda: 10.0,
        sleep=lambda _: None,
        tail_factory=lambda _: RaisingTail(PermissionError("owned log denied")),
        terminate_tree=lambda _: (_ for _ in ()).throw(OSError("taskkill failed")),
    )
    deps = replace(deps, spawn=spawn, monitor=monitor)

    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(), tmp_path / "artifacts", dry_run=False
    )

    assert result.outcome is not None
    assert result.outcome.state == "crash"
    assert result.outcome.failure_reason == "termination-failure"
    assert result.paths.report_json_path.is_file()


def test_relative_output_directory_becomes_absolute_before_it_reaches_faf(tmp_path: Path) -> None:
    deps, _, _, _ = _deps(tmp_path)
    repository = tmp_path / "repo"
    repository.mkdir(exist_ok=True)

    result = Runner(repository, deps).run(
        RunConfig(), Path("artifacts/runs"), dry_run=True
    )

    assert result.paths.run_dir.is_absolute()
    assert result.paths.run_dir.is_relative_to(repository.resolve())
    assert Path(result.argv[result.argv.index("/log") + 1]).is_absolute()
    assert Path(result.argv[result.argv.index("/savereplay") + 1]).is_absolute()


def test_real_runner_writes_one_immutable_manifest_and_deterministic_reports(tmp_path: Path) -> None:
    deps, layout, _, spawn = _deps(tmp_path)
    output = tmp_path / "artifacts"

    result = Runner(tmp_path / "repo", deps).run(RunConfig(), output, dry_run=False)

    assert layout.generated_init.is_file()
    assert len(spawn.calls) == 1
    argv, cwd = spawn.calls[0]
    assert isinstance(argv, list)
    assert cwd == layout.executable.parent
    manifest = json.loads(result.paths.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-fixed"
    assert manifest["faf"]["hashes"]["executable"]
    assert manifest["faf"]["commit"] == "602185eb0753d205080313cc294d5665b49681cb"
    assert manifest["overmind4"]["git_commit"] == "abc123"
    assert manifest["overmind4"]["content_sha256"] == "content123"
    assert manifest["config_sha256"]
    assert manifest["map"] == {"id": "SCMP_007", "sha256": "map123", "version": 3}
    assert manifest["active_sim_mod_uids"] == ["0d46fbb2-beeb-4bde-b3c6-8bac28232a4b"]
    assert manifest["argv"] == argv
    assert manifest["artifacts"]["prefs"] == str(result.paths.prefs_path)
    prefs_argument = argv[argv.index("/prefs") + 1]
    assert prefs_argument == "Overmind4-run-fixed.prefs"
    assert prefs_argument == Path(prefs_argument).name
    assert not (deps.preferences_directory / prefs_argument).exists()
    prefs_text = result.paths.prefs_path.read_text(encoding="utf-8")
    assert "current = 1" in prefs_text
    assert "Name = 'Overmind4 Harness'" in prefs_text
    assert "options = {" in prefs_text
    assert "active_mods = { }" in prefs_text
    assert result.paths.report_json_path.is_file()
    assert result.paths.report_markdown_path.is_file()
    report = json.loads(result.paths.report_json_path.read_text(encoding="utf-8"))
    assert report["completed_at"] == "2026-08-10T12:00:00Z"
    assert report["artifacts_present"] == {"log": False, "replay": False}
    assert "achieved_sim_speed" in report


def test_isolated_prefs_collision_is_refused_without_overwrite_or_launch(
    tmp_path: Path,
) -> None:
    deps, _, _, spawn = _deps(tmp_path)
    deps.preferences_directory.mkdir(parents=True)
    existing = deps.preferences_directory / "Overmind4-run-fixed.prefs"
    existing.write_text("user-owned", encoding="utf-8")

    with pytest.raises(FileExistsError, match="isolated prefs file already exists"):
        Runner(tmp_path / "repo", deps).run(
            RunConfig(), tmp_path / "artifacts", dry_run=False
        )

    assert existing.read_text(encoding="utf-8") == "user-owned"
    assert spawn.calls == []


def test_spawn_failure_removes_only_the_exact_owned_transient_prefs(
    tmp_path: Path,
) -> None:
    deps, _, _, _ = _deps(tmp_path)
    deps.preferences_directory.mkdir(parents=True)
    unrelated = deps.preferences_directory / "Game.prefs"
    unrelated.write_text("user-owned", encoding="utf-8")

    def fail_spawn(_: list[str], __: Path) -> FakeProcess:
        raise OSError("launch failed")

    deps = replace(deps, spawn=fail_spawn)
    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(), tmp_path / "artifacts", dry_run=False
    )

    assert result.outcome is not None
    assert result.outcome.state == "crash"
    assert not (deps.preferences_directory / "Overmind4-run-fixed.prefs").exists()
    assert unrelated.read_text(encoding="utf-8") == "user-owned"


def test_transient_prefs_cleanup_failure_is_contained_and_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps, _, _, _ = _deps(tmp_path)
    owned_prefs = (
        deps.preferences_directory / "Overmind4-run-fixed.prefs"
    ).resolve()
    original_unlink = Path.unlink

    def fail_owned_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.resolve() == owned_prefs:
            raise PermissionError("owned prefs is locked")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_owned_unlink)

    result = Runner(tmp_path / "repo", deps).run(
        RunConfig(), tmp_path / "artifacts", dry_run=False
    )

    assert result.outcome is not None
    assert result.outcome.state == "crash"
    assert result.outcome.failure_reason == "preferences-cleanup-error:PermissionError"
    assert result.paths.report_json_path.is_file()
    assert owned_prefs.is_file()


def test_manifest_creation_refuses_run_id_collision_instead_of_overwriting(tmp_path: Path) -> None:
    deps, _, _, _ = _deps(tmp_path)
    output = tmp_path / "artifacts"
    runner = Runner(tmp_path / "repo", deps)
    runner.run(RunConfig(), output, dry_run=False)

    with pytest.raises(FileExistsError):
        runner.run(RunConfig(), output, dry_run=False)
