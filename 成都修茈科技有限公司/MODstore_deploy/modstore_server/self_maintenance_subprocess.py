"""Bounded subprocess helpers for self-maintenance merge and policy flows."""

from __future__ import annotations

import codecs
import io
import locale
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, cast


def terminate_subprocess(
    proc: subprocess.Popen[bytes],
    *,
    grace_seconds: float = 0.25,
    process_group: bool = False,
) -> None:
    """Reap the child and, when explicitly owned, its POSIX process group."""
    owns_group = process_group and os.name == "posix"

    def send(sig: int) -> None:
        try:
            if owns_group:
                os.killpg(proc.pid, sig)
            elif proc.poll() is None:
                if sig == signal.SIGTERM:
                    proc.terminate()
                else:
                    proc.kill()
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # A child can exit while its descendants still own the stdout pipe.
        # Only this helper's start_new_session group is ever signalled.
        send(signal.SIGKILL if os.name == "posix" else signal.SIGTERM)
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=max(grace_seconds, 1.0))


class _ExcerptReader:
    """Drain the pipe without retaining output beyond the requested character cap."""

    def __init__(self, stdout: io.BufferedReader, max_chars: int) -> None:
        self.stdout = stdout
        self.max_chars = max_chars
        self.chunks: list[str] = []
        self.collected = 0
        self.capped_at: float | None = None
        self.error: OSError | None = None
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.read, name="command-excerpt", daemon=True)

    def read(self) -> None:
        decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace"),
            translate=True,
        )
        try:
            while True:
                block = self.stdout.read1(8192)
                text = decoder.decode(block, final=not block)
                with self.lock:
                    if self.collected < self.max_chars:
                        kept = text[: self.max_chars - self.collected]
                        self.chunks.append(kept)
                        self.collected += len(kept)
                        if self.collected >= self.max_chars:
                            self.capped_at = time.monotonic()
                            self.changed.set()
                if not block:
                    break
        except OSError as exc:
            self.error = exc
        finally:
            self.stdout.close()
            self.done.set()
            self.changed.set()

    def snapshot(self) -> tuple[str, float | None]:
        with self.lock:
            return "".join(self.chunks).strip(), self.capped_at


def run_cmd_excerpt(
    args: List[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 120,
    max_chars: int = 20000,
) -> str:
    """Return bounded output with a deadline covering both pipe reads and exit.

    After reaching the cap, drain for up to one second to observe a natural
    failure. A continuing producer is then stopped without closing its pipe
    prematurely and manufacturing a BrokenPipeError. POSIX descendants share
    an owned process group and are also stopped on exit or timeout.
    """
    if max_chars <= 0:
        return ""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )
    stdout = proc.stdout
    if stdout is None:
        terminate_subprocess(proc, process_group=True)
        raise RuntimeError(f"command produced no stdout pipe: {' '.join(args)}")
    reader = _ExcerptReader(cast(io.BufferedReader, stdout), max_chars)
    reader.thread.start()
    try:
        while True:
            excerpt, capped_at = reader.snapshot()
            rc = proc.poll()
            if rc is not None and reader.done.is_set():
                if reader.error is not None:
                    raise RuntimeError(
                        f"command output read failed: {' '.join(args)}"
                    ) from reader.error
                if rc != 0:
                    raise RuntimeError(f"command failed ({rc}): {' '.join(args)}\n{excerpt}")
                return excerpt
            now = time.monotonic()
            if now >= deadline:
                raise RuntimeError(
                    f"command timed out after {timeout}s: {' '.join(args)}\n{excerpt}"
                )
            if capped_at is not None and now >= capped_at + 1.0:
                terminated_by_us = rc is None
                terminate_subprocess(proc, process_group=True)
                rc = proc.returncode
                if rc != 0 and not (
                    terminated_by_us and rc in {-int(signal.SIGTERM), 128 + int(signal.SIGTERM)}
                ):
                    raise RuntimeError(f"command failed ({rc}): {' '.join(args)}\n{excerpt}")
                return excerpt
            next_event = min(deadline, capped_at + 1.0) if capped_at is not None else deadline
            reader.changed.wait(timeout=min(0.05, max(0.0, next_event - now)))
            reader.changed.clear()
    finally:
        terminate_subprocess(proc, process_group=True)
        reader.thread.join(timeout=1.0)
        # On Windows an inherited descendant pipe can outlive the direct child.
        # Do not block the caller closing a pipe still held by the reader thread.
        if not reader.thread.is_alive():
            stdout.close()
