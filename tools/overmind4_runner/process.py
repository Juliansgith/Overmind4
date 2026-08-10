from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Protocol

from .parsing import ProcessObservation


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...


class IncrementalTail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0

    def read_new(self) -> str:
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
                self.offset = handle.tell()
        except FileNotFoundError:
            return ""
        return data.decode("utf-8", errors="replace")


def detect_fail_fast(chunk: str) -> str | None:
    lowered = chunk.lower()
    patterns = (
        ("om4harness|v=1|kind=failure", "harness-failure"),
        ("desync", "desync"),
        ("lua error", "lua-error"),
        ("error importing", "import-error"),
        ("unable to load map", "map-load-error"),
        ("exception_access_violation", "engine-crash"),
    )
    for needle, reason in patterns:
        if needle in lowered:
            return reason
    return None


def spawn_owned(argv: list[str], cwd: Path) -> subprocess.Popen[bytes]:
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        argv,
        cwd=str(cwd),
        shell=False,
        creationflags=creation_flags,
    )


def terminate_owned_tree(pid: int) -> None:
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError("owned process PID must be a positive integer")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


class Monitor:
    def __init__(
        self,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        tail_factory: Callable[[Path], IncrementalTail] = IncrementalTail,
        terminate_tree: Callable[[int], None] = terminate_owned_tree,
        poll_interval: float = 0.1,
    ) -> None:
        self._now = now
        self._sleep = sleep
        self._tail_factory = tail_factory
        self._terminate_tree = terminate_tree
        self._poll_interval = poll_interval

    def _stop_owned(self, process: ProcessHandle) -> tuple[int | None, bool]:
        cleanup_failed = False
        try:
            self._terminate_tree(process.pid)
        except Exception:
            cleanup_failed = True
        try:
            process.wait(timeout=5)
        except Exception:
            cleanup_failed = True
        try:
            return process.poll(), cleanup_failed
        except Exception:
            return None, True

    def wait(
        self,
        process: ProcessHandle,
        owned_log_path: Path,
        wall_timeout: float,
    ) -> ProcessObservation:
        started = self._now()
        tail = self._tail_factory(owned_log_path)
        timeout = False
        fail_fast_reason: str | None = None
        exit_code: int | None = None

        while True:
            fail_fast_reason = detect_fail_fast(tail.read_new())
            if fail_fast_reason:
                exit_code, cleanup_failed = self._stop_owned(process)
                if cleanup_failed:
                    fail_fast_reason = "termination-failure"
                break

            exit_code = process.poll()
            if exit_code is not None:
                break

            if self._now() - started >= wall_timeout:
                timeout = True
                exit_code, cleanup_failed = self._stop_owned(process)
                if cleanup_failed:
                    fail_fast_reason = "termination-failure"
                break
            self._sleep(self._poll_interval)

        return ProcessObservation(
            exit_code=exit_code,
            wall_seconds=max(0.0, self._now() - started),
            wall_timeout=timeout,
            fail_fast_reason=fail_fast_reason,
        )
