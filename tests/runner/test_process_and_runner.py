from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tools.overmind4_runner.installation import RuntimeLayout
from tools.overmind4_runner.model import RunConfig
from tools.overmind4_runner.process import Monitor, terminate_owned_tree
from tools.overmind4_runner.runner import Runner, RunnerDependencies


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


class FakeTail:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = iter(chunks)

    def read_new(self) -> str:
        return next(self.chunks, "")


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
    assert layout.source_init.read_bytes() == source_before
    assert spawn.calls == []


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
    assert result.paths.report_json_path.is_file()
    assert result.paths.report_markdown_path.is_file()


def test_manifest_creation_refuses_run_id_collision_instead_of_overwriting(tmp_path: Path) -> None:
    deps, _, _, _ = _deps(tmp_path)
    output = tmp_path / "artifacts"
    runner = Runner(tmp_path / "repo", deps)
    runner.run(RunConfig(), output, dry_run=False)

    with pytest.raises(FileExistsError):
        runner.run(RunConfig(), output, dry_run=False)
