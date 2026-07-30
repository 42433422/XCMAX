"""Bounded subprocess helpers for self-maintenance merge and policy flows."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from typing import List, Optional


def terminate_subprocess(proc: subprocess.Popen[str], *, grace_seconds: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=grace_seconds)


def _truncation_terminate_exit_ok(
    returncode: int, *, terminated_by_us: bool, reader_closed: bool
) -> bool:
    """Return True when a truncated read ended safely (terminate or broken pipe)."""

    if returncode == 0:
        return True
    if terminated_by_us:
        sigterm = int(signal.SIGTERM)
        if returncode < 0:
            return returncode == -sigterm
        if returncode == 128 + sigterm:
            return True
    if reader_closed:
        sigpipe = int(signal.SIGPIPE)
        if returncode < 0:
            return returncode == -sigpipe
        if returncode in {128 + sigpipe, 120}:
            return True
    return False


def run_cmd_excerpt(
    args: List[str],
    *,
    cwd: Optional[Path] = None,
    timeout: int = 120,
    max_chars: int = 20000,
) -> str:
    """Run a command and return at most ``max_chars`` of combined stdout/stderr.

    When output exceeds ``max_chars``, the child is terminated promptly so a large
    producer (e.g. ``git diff``) cannot block on a full pipe buffer. Non-zero
    exit codes are still enforced on the truncation path unless the child was
    stopped by our SIGTERM after a successful partial read.
    """

    if max_chars <= 0:
        return ""
    proc = subprocess.Popen(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    stdout = proc.stdout
    if stdout is None:
        raise RuntimeError(f"command produced no stdout pipe: {' '.join(args)}")
    chunks: List[str] = []
    collected = 0
    truncated = False
    try:
        while collected < max_chars:
            block = stdout.read(min(8192, max_chars - collected))
            if not block:
                break
            chunks.append(block)
            collected += len(block)
        truncated = collected >= max_chars
        excerpt = "".join(chunks).strip()
        if truncated:
            stdout.close()
            terminated_by_us = False
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                terminated_by_us = True
                terminate_subprocess(proc)
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5.0)
            rc = proc.returncode if proc.returncode is not None else -1
            if not _truncation_terminate_exit_ok(
                int(rc), terminated_by_us=terminated_by_us, reader_closed=True
            ):
                raise RuntimeError(f"command failed ({rc}): {' '.join(args)}\n{excerpt}")
            return excerpt
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_subprocess(proc)
            raise RuntimeError(
                f"command timed out after {timeout}s: {' '.join(args)}\n{excerpt}"
            ) from None
        if proc.returncode != 0:
            raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{excerpt}")
        return excerpt
    finally:
        if not stdout.closed:
            stdout.close()
