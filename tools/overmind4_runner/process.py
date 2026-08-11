from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Protocol

from .parsing import (
    ProcessObservation,
    detect_engine_failure,
    harness_marker_fields,
    is_stock_platoon_trace_frame,
    is_stock_platoon_traceback_label,
    is_stock_platoon_warning_header,
    is_trace_continuation,
    overmind_marker_fields,
)


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


class _FailFastScanner:
    def __init__(self, *, run_id: str | None, our_slot: int | None) -> None:
        self.run_id = run_id
        self.our_slot = our_slot
        self.fragment = ""
        self.stock_warning_candidate: list[str] | None = None
        self.failure_reason: str | None = None
        self.sim_timeout = False
        self.lifecycle_stage = 0

    @property
    def startup_complete(self) -> bool:
        return self.lifecycle_stage == 4

    def _matching_harness_fields(self, line: str) -> dict[str, str] | None:
        fields = harness_marker_fields(line)
        if (
            not fields
            or self.run_id is None
            or fields.get("v") != "1"
            or fields.get("run") != self.run_id
        ):
            return None
        return fields

    def _advance_lifecycle(self, line: str) -> None:
        harness_fields = self._matching_harness_fields(line)
        if harness_fields:
            kind = harness_fields.get("kind")
            if kind == "start" and self.lifecycle_stage == 0:
                self.lifecycle_stage = 1
            elif kind == "speed" and self.lifecycle_stage == 3:
                self.lifecycle_stage = 4

        brain_fields = overmind_marker_fields(line)
        if (
            not brain_fields
            or brain_fields.get("v") != "1"
            or brain_fields.get("kind") != "lifecycle"
            or self.our_slot is None
        ):
            return
        try:
            army = int(brain_fields.get("army", ""))
        except ValueError:
            return
        if army != self.our_slot:
            return
        event = brain_fields.get("event")
        if event == "created" and self.lifecycle_stage == 1:
            self.lifecycle_stage = 2
        elif event == "begin_session" and self.lifecycle_stage == 2:
            self.lifecycle_stage = 3

    def _process_regular_line(self, line: str) -> None:
        self._advance_lifecycle(line)
        fields = self._matching_harness_fields(line)
        if fields and fields.get("kind") == "failure":
            self.failure_reason = fields.get("reason") or "harness-failure"
            return
        if fields and fields.get("kind") == "timeout":
            self.sim_timeout = True
            return

        if is_stock_platoon_warning_header(line):
            if self.startup_complete:
                self.stock_warning_candidate = [line]
            else:
                self.failure_reason = "lua-error"
            return

        engine_failure = detect_engine_failure(line)
        if engine_failure:
            self.failure_reason = engine_failure

    def _process_line(self, line: str) -> None:
        if self.failure_reason:
            return
        candidate = self.stock_warning_candidate
        if candidate is None:
            self._process_regular_line(line)
            return
        if len(candidate) == 1:
            if is_stock_platoon_traceback_label(line):
                candidate.append(line)
            else:
                self.failure_reason = "lua-error"
            return
        if len(candidate) == 2:
            if is_stock_platoon_trace_frame(line):
                candidate.append(line)
            else:
                self.failure_reason = "lua-error"
            return
        if not line.strip():
            return
        if is_trace_continuation(line):
            self.failure_reason = "lua-error"
            return
        self.stock_warning_candidate = None
        self._process_regular_line(line)

    def feed(self, chunk: str) -> str | None:
        if self.failure_reason or not chunk:
            return self.failure_reason
        buffer = self.fragment + chunk
        trailing_cr = buffer.endswith("\r")
        if trailing_cr:
            buffer = buffer[:-1]
        parts = buffer.splitlines(keepends=True)
        self.fragment = ""
        if parts and not parts[-1].endswith(("\n", "\r")):
            self.fragment = parts.pop()
        if trailing_cr:
            self.fragment += "\r"
        for part in parts:
            self._process_line(part.rstrip("\r\n"))
            if self.failure_reason:
                break
        return self.failure_reason

    def finish(self) -> str | None:
        if self.failure_reason:
            return self.failure_reason
        if self.fragment:
            fragment = self.fragment
            self.fragment = ""
            self._process_line(fragment)
        if self.failure_reason:
            return self.failure_reason
        if self.stock_warning_candidate is not None:
            if len(self.stock_warning_candidate) != 3:
                self.failure_reason = "lua-error"
            self.stock_warning_candidate = None
        return self.failure_reason


def detect_fail_fast(
    chunk: str,
    *,
    run_id: str | None = None,
    our_slot: int | None = None,
) -> str | None:
    scanner = _FailFastScanner(run_id=run_id, our_slot=our_slot)
    return scanner.feed(chunk) or scanner.finish()


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
        our_slot: int | None = None,
    ) -> ProcessObservation:
        started: float | None = None
        timeout = False
        sim_timeout = False
        fail_fast_reason: str | None = None
        exit_code: int | None = None

        try:
            started = self._now()
            tail = self._tail_factory(owned_log_path)
            scanner = _FailFastScanner(run_id=run_id, our_slot=our_slot)
            while True:
                fail_fast_reason = scanner.feed(tail.read_new())
                if fail_fast_reason:
                    exit_code, cleanup_failed = self.stop_owned(process)
                    if cleanup_failed:
                        fail_fast_reason = "termination-failure"
                    break

                if scanner.sim_timeout:
                    sim_timeout = True
                    exit_code, cleanup_failed = self.stop_owned(process)
                    if cleanup_failed:
                        fail_fast_reason = "termination-failure"
                    break

                exit_code = process.poll()
                if exit_code is not None:
                    fail_fast_reason = scanner.finish()
                    break

                if self._now() - started >= wall_timeout:
                    fail_fast_reason = scanner.finish()
                    timeout = fail_fast_reason is None
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
