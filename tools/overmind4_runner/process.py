from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Protocol

from .parsing import ProcessObservation, detect_engine_failure, harness_marker_fields


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


def detect_fail_fast(chunk: str, *, run_id: str | None = None) -> str | None:
    for line in chunk.splitlines():
        fields = harness_marker_fields(line)
        if (
            fields
            and run_id is not None
            and fields.get("v") == "1"
            and fields.get("run") == run_id
            and fields.get("kind") == "failure"
        ):
            return fields.get("reason") or "harness-failure"
        engine_failure = detect_engine_failure(line)
        if engine_failure:
            return engine_failure
    return None


def _has_structured_sim_timeout(chunk: str, run_id: str | None) -> bool:
    if run_id is None:
        return False
    for line in chunk.splitlines():
        fields = harness_marker_fields(line)
        if (
            fields
            and fields.get("v") == "1"
            and fields.get("run") == run_id
            and fields.get("kind") == "timeout"
        ):
            return True
    return False


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

    def stop_owned(self, process: ProcessHandle) -> tuple[int | None, bool]:
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
        *,
        run_id: str | None = None,
    ) -> ProcessObservation:
        started: float | None = None
        timeout = False
        sim_timeout = False
        fail_fast_reason: str | None = None
        exit_code: int | None = None
        pending_line = ""

        try:
            started = self._now()
            tail = self._tail_factory(owned_log_path)
            while True:
                scan_text = pending_line + tail.read_new()
                last_newline = max(scan_text.rfind("\n"), scan_text.rfind("\r"))
                pending_line = scan_text[last_newline + 1 :] if last_newline >= 0 else scan_text
                fail_fast_reason = detect_fail_fast(scan_text, run_id=run_id)
                if fail_fast_reason:
                    exit_code, cleanup_failed = self.stop_owned(process)
                    if cleanup_failed:
                        fail_fast_reason = "termination-failure"
                    break

                if _has_structured_sim_timeout(scan_text, run_id):
                    sim_timeout = True
                    exit_code, cleanup_failed = self.stop_owned(process)
                    if cleanup_failed:
                        fail_fast_reason = "termination-failure"
                    break

                exit_code = process.poll()
                if exit_code is not None:
                    break

                if self._now() - started >= wall_timeout:
                    timeout = True
                    exit_code, cleanup_failed = self.stop_owned(process)
                    if cleanup_failed:
                        fail_fast_reason = "termination-failure"
                    break
                self._sleep(self._poll_interval)
        except Exception as error:
            exit_code, cleanup_failed = self.stop_owned(process)
            fail_fast_reason = (
                "termination-failure"
                if cleanup_failed
                else f"process-monitor-error:{type(error).__name__}"
            )
        except BaseException:
            self.stop_owned(process)
            raise

        try:
            wall_seconds = 0.0 if started is None else max(0.0, self._now() - started)
        except Exception:
            wall_seconds = 0.0

        return ProcessObservation(
            exit_code=exit_code,
            wall_seconds=wall_seconds,
            wall_timeout=timeout,
            fail_fast_reason=fail_fast_reason,
            sim_timeout=sim_timeout,
        )
