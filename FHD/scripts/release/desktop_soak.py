#!/usr/bin/env python3
"""Measure an installed desktop on an isolated native acceptance account.

Playwright drives the real renderer; psutil observes only this launch's process
tree. Raw measurements are checkpointed even on failure. The independent
verifier, not this producer, decides whether the two platforms qualify.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psutil
from verify_desktop_soak import (
    MAX_HANDLES,
    MAX_RENDERER_EVENTS,
    MAX_RSS_BYTES,
    MIN_DURATION_SECONDS,
    verify_platform,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checkpoint(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def artifact_identity(binary: Path, release_sha: str, version: str) -> tuple[dict, Path]:
    resources = (
        binary.parent.parent / "Resources"
        if platform.system() == "Darwin"
        else binary.parent / "resources"
    )
    identity = resources / "build-info.json"
    build = json.loads(identity.read_text(encoding="utf-8-sig"))
    if build.get("gitSha") != release_sha or build.get("version") != version:
        raise ValueError("installed_build_identity_mismatch")
    backend_name = "xcagi-backend.exe" if platform.system() == "Windows" else "xcagi-backend"
    candidates = [
        resources / "backend" / sub / backend_name for sub in ("", "xcagi-backend", "_internal")
    ]
    backend = next((candidate for candidate in candidates if candidate.is_file()), None)
    if backend is None:
        raise ValueError("packaged_backend_missing")
    return {
        "executable_sha256": digest(binary),
        "build_info_sha256": digest(identity),
        "app_asar_sha256": digest(resources / "app.asar"),
        "backend_sha256": digest(backend),
        "build_sha": release_sha,
        "version": version,
    }, backend


def probe(client: httpx.Client, release_sha: str) -> dict[str, bool]:
    checks = {}
    for endpoint in ("/api/ping", "/api/health", "/api/desktop/status"):
        try:
            response = client.get(endpoint)
            body = response.json()
            valid = response.status_code == 200 and isinstance(body, dict)
            if endpoint == "/api/ping":
                valid = valid and body.get("pong") is True
            elif endpoint == "/api/health":
                runtime = body.get("runtime") if valid else None
                valid = (
                    valid
                    and body.get("status") == "healthy"
                    and body.get("git_sha") == release_sha
                    and isinstance(runtime, dict)
                    and runtime.get("status") == "healthy"
                    and runtime.get("blockers") == []
                    and body.get("degradedReasons") == []
                )
            else:
                runtime = body.get("runtimeIntegrity") if valid else None
                valid = (
                    valid
                    and body.get("desktopMode") is True
                    and body.get("readyForUi") is True
                    and body.get("runtimeStatus") == "healthy"
                    and body.get("degraded") is False
                    and body.get("degradedReasons") == []
                    and isinstance(runtime, dict)
                    and runtime.get("status") == "healthy"
                    and runtime.get("blockers") == []
                )
            checks[endpoint] = bool(valid)
        except (httpx.HTTPError, ValueError, AttributeError):
            checks[endpoint] = False
    return checks


class ProcessTree:
    """Retain process identities across reparenting; never act on recycled PIDs."""

    def __init__(self, pid: int, binary: Path, backend: Path):
        self.root = psutil.Process(pid)
        self.binary, self.backend = binary, backend
        self.known: dict[tuple[int, float], psutil.Process] = {
            (pid, self.root.create_time()): self.root
        }
        self.previous_cpu: dict[tuple[int, float], float] = {}
        self.previous_at = time.monotonic()

    def living(self) -> list[psutil.Process]:
        try:
            children = self.root.children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for process in [self.root, *children]:
            try:
                self.known[(process.pid, process.create_time())] = process
            except psutil.NoSuchProcess:
                continue
        living = []
        for key, process in list(self.known.items()):
            try:
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    living.append(process)
                    continue
            except psutil.NoSuchProcess:
                pass
            self.known.pop(key, None)
        return living

    def sample(self) -> dict:
        if not self.root.is_running() or not Path(self.root.exe()).samefile(self.binary):
            raise ValueError("desktop_process_missing_or_replaced")
        processes = self.living()
        owners = [
            p
            for p in processes
            if p.ppid() == self.root.pid and Path(p.exe()).samefile(self.backend)
        ]
        if len(owners) != 1:
            raise ValueError("owned_backend_missing_or_ambiguous")
        now, rss, handles, used = time.monotonic(), 0, 0, 0.0
        current = {}
        for process in processes:
            with process.oneshot():
                key = (process.pid, process.create_time())
                cpu = process.cpu_times()
                current[key] = cpu.user + cpu.system
                # A new child contributes its observed lifetime CPU; missing data never becomes zero.
                used += max(0, current[key] - self.previous_cpu.get(key, 0))
                rss += process.memory_info().rss
                handles += process.num_handles() if os.name == "nt" else process.num_fds()
        cpu_percent = 100 * used / max(now - self.previous_at, 0.001) / (psutil.cpu_count() or 1)
        if not self.previous_cpu:
            cpu_percent = 0.0  # The first observation establishes the interval baseline.
        self.previous_at, self.previous_cpu = now, current
        backend = owners[0]
        return {
            "root_pid": self.root.pid,
            "root_create_time": self.root.create_time(),
            "backend_pid": backend.pid,
            "backend_create_time": backend.create_time(),
            "rss_bytes": rss,
            "cpu_percent": cpu_percent,
            "handles": handles,
            "process_count": len(processes),
        }

    def cleanup(self) -> int:
        incomplete = 0
        try:
            processes = self.living()
        except psutil.AccessDenied:
            processes = list(self.known.values())
            incomplete = 1
        for process in reversed(processes):
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                incomplete = 1
        _, alive = psutil.wait_procs(processes, timeout=10)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                incomplete = 1
        _, alive = psutil.wait_procs(alive, timeout=10)
        return len(alive) + incomplete


class Desktop:
    def __init__(self, args, playwright, profile: Path, backend: Path, report: dict):
        self.args, self.playwright, self.profile, self.backend = args, playwright, profile, backend
        self.report = report
        self.observed_pages = set()
        self.port, self.cdp_port = free_port(), free_port()
        while self.cdp_port == self.port:
            self.cdp_port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.tree = self.browser = self.child = None
        self.client = httpx.Client(
            base_url=self.base, timeout=10, trust_env=False, follow_redirects=False
        )
        self.account = None

    def record_event(self, kind: str, error=None) -> None:
        events = self.report["events"]
        if len(events) >= MAX_RENDERER_EVENTS:
            if "renderer_event_limit_exceeded" in self.report["blockers"]:
                return
            self.report["blockers"].append("renderer_event_limit_exceeded")
        else:
            phase = self.report["phase"]
            event = {"kind": kind, "phase": phase, "timestamp_utc": utc_now()}
            if error is not None:
                event["message_sha256"] = hashlib.sha256(str(error).encode()).hexdigest()
            events.append(event)
            if (kind, phase) != ("renderer_crash", "renderer_crash"):
                if "unexpected_renderer_event" not in self.report["blockers"]:
                    self.report["blockers"].append("unexpected_renderer_event")
        try:
            checkpoint(self.args.output, self.report)
        except (OSError, ValueError):
            if "renderer_event_checkpoint_failed" not in self.report["blockers"]:
                self.report["blockers"].append("renderer_event_checkpoint_failed")

    def observe_page(self, page) -> None:
        if page not in self.observed_pages:
            self.observed_pages.add(page)
            page.on("crash", lambda *_: self.record_event("renderer_crash"))
            page.on("pageerror", lambda error: self.record_event("renderer_page_error", error))
            page.on("close", lambda *_: self.observed_pages.discard(page))

    async def attach(self) -> None:
        if self.browser is None:
            self.browser = await self.playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{self.cdp_port}", timeout=10000
            )
        for _ in range(60):
            pages = [
                p
                for context in self.browser.contexts
                for p in context.pages
                if p.url.startswith(self.base + "/")
            ]
            if pages:
                for page in pages:
                    self.observe_page(page)
                self.page = pages[0]
                self.page.set_default_timeout(15000)
                return
            await asyncio.sleep(1)
        raise ValueError("desktop_renderer_target_missing")

    async def launch(self) -> None:
        env = dict(
            os.environ,
            XCAGI_DESKTOP_USER_DATA_DIR=str(self.profile),
            XCAGI_DESKTOP_PORT=str(self.port),
        )
        # Test/stub and external-runtime overrides cannot participate in installed acceptance.
        forbidden = (
            "XCAGI_DESKTOP_E2E",
            "XCAGI_DESKTOP_TEST",
            "NODE_OPTIONS",
            "ELECTRON_RUN_AS_NODE",
        )
        if any(env.get(key) for key in forbidden):
            raise ValueError("test_or_runtime_override_present")
        self.child = subprocess.Popen(
            [
                str(self.args.binary),
                f"--remote-debugging-port={self.cdp_port}",
                "--remote-debugging-address=127.0.0.1",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.tree = ProcessTree(self.child.pid, self.args.binary, self.backend)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            self.tree.living()
            if self.child.poll() is not None:
                raise ValueError("desktop_exited_before_ready")
            try:
                if all(probe(self.client, self.args.release_sha).values()):
                    await self.attach()
                    self.tree.sample()
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        raise ValueError("installed_desktop_readiness_timeout")

    async def identity(self) -> bool:
        identity = await self.page.evaluate("() => window.xcagiDesktop.getAppIdentity()")
        data_dir = await self.page.evaluate("() => window.xcagiDesktop.getDataDir()")
        if (
            identity.get("isPackaged") is not True
            or identity.get("version") != self.args.product_version
        ):
            raise ValueError("renderer_installed_identity_mismatch")
        if Path(data_dir).resolve() != self.profile.resolve():
            raise ValueError("desktop_profile_isolation_failed")
        return True

    async def login(self) -> None:
        await self.page.goto(self.base + "/login", wait_until="domcontentloaded")
        await self.page.locator("#lv-username").fill(os.environ["XCAGI_TEST_USER"])
        await self.page.locator("#lv-password").fill(os.environ["XCAGI_TEST_PASS"])
        await self.page.locator(".login-form button[type=submit]").click()
        await self.page.locator("#lv-password").wait_for(state="detached", timeout=60000)
        self.account = await self.account_identity()

    async def account_identity(self) -> str:
        response = await self.page.request.get(
            self.base + "/api/auth/me", timeout=10000, max_redirects=0
        )
        body = await response.json()
        data = body.get("data") or {}
        user = data.get("user") or {}
        tenant = data.get("tenant_id") or user.get("tenant_id")
        if (
            response.status != 200
            or body.get("success") is not True
            or not user.get("id")
            or not tenant
        ):
            raise ValueError("authenticated_enterprise_identity_missing")
        return hashlib.sha256(json.dumps([user["id"], tenant], sort_keys=True).encode()).hexdigest()

    async def navigate(self, key: str) -> None:
        entry = self.page.locator(
            f'[data-tour="sidebar-{key}"]:visible,[data-tour="sidebar-mod-erp-{key}"]:visible'
        ).first
        if not await entry.is_visible():
            for parent in await self.page.locator(
                ".sidebar .menu-item.has-children:not(.expanded)"
            ).all():
                await parent.click()
        await entry.click()
        await self.page.locator(f"#view-{key}").wait_for(state="visible")
        if key == "settings":
            from playwright.async_api import expect

            version = self.page.locator(".settings-card--about summary .settings-row__meta")
            await version.scroll_into_view_if_needed()
            await expect(version).to_have_text(self.args.product_version)
        await self.identity()

    async def ready_again(self, previous_backend: int | None = None) -> dict:
        from playwright.async_api import Error as PlaywrightError

        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if all(probe(self.client, self.args.release_sha).values()):
                try:
                    measured = self.tree.sample()
                except (psutil.NoSuchProcess, ValueError):
                    await asyncio.sleep(1)
                    continue
                if measured["backend_pid"] == previous_backend:
                    await asyncio.sleep(1)
                    continue
                try:
                    await self.navigate("settings")
                except PlaywrightError:
                    await asyncio.sleep(1)
                    continue
                if await self.account_identity() != self.account:
                    raise ValueError("recovery_changed_account_or_tenant")
                return measured
            await asyncio.sleep(1)
        raise ValueError("fault_recovery_timeout")

    async def quit(self) -> int:
        from playwright.async_api import Error as PlaywrightError

        self.tree.living()  # Snapshot descendants before Electron releases their parent.
        try:
            await self.page.keyboard.press(
                "Meta+Q" if platform.system() == "Darwin" else "Control+Q"
            )
        except PlaywrightError:
            pass  # The target may close before key-up; process and lifecycle proofs still apply.
        await asyncio.to_thread(self.child.wait, timeout=30)
        _, remaining = await asyncio.to_thread(
            psutil.wait_procs, list(self.tree.known.values()), timeout=15
        )
        lifetime = json.loads((self.profile / "session-lifecycle.json").read_text())
        if remaining or lifetime.get("clean") is not True or lifetime.get("pid") != self.child.pid:
            raise ValueError("unclean_exit_or_orphan_processes")
        await self.browser.close()
        self.browser = None
        return 0

    async def scenario(self, name: str) -> dict:
        from playwright.async_api import Error as PlaywrightError

        result = {"started_at": utc_now(), "passed": False}
        if name == "renderer_offline":
            session = await self.page.context.new_cdp_session(self.page)
            try:
                await session.send("Network.enable")
                await session.send(
                    "Network.emulateNetworkConditions",
                    {
                        "offline": True,
                        "latency": 0,
                        "downloadThroughput": -1,
                        "uploadThroughput": -1,
                    },
                )
                result["offline_observed"] = await self.page.evaluate(
                    "async () => { try { await fetch('/api/ping', {cache:'no-store',signal:AbortSignal.timeout(5000)}); return false } catch { return true } }"
                )
            finally:
                await session.send(
                    "Network.emulateNetworkConditions",
                    {
                        "offline": False,
                        "latency": 0,
                        "downloadThroughput": -1,
                        "uploadThroughput": -1,
                    },
                )
                await session.detach()
            await self.ready_again()
            result["recovered"] = True
        elif name == "renderer_crash":
            crashed = asyncio.Event()

            def observed_crash(*_):
                crashed.set()

            crashed_page = self.page
            crashed_page.on("crash", observed_crash)
            session = await crashed_page.context.new_cdp_session(crashed_page)
            try:
                try:
                    await asyncio.wait_for(session.send("Page.crash"), timeout=10)
                except (PlaywrightError, TimeoutError):
                    pass  # The crash event, rather than a disconnected command, is the proof.
                await asyncio.wait_for(crashed.wait(), timeout=10)
                # A Playwright Page stays crashed even when the product reloads its renderer.
                # Reattach the observer to the same application; never restart it to mask failure.
                await self.browser.close()
                self.browser = None
                await self.attach()
                await self.ready_again()
                result.update(crashed_observed=crashed.is_set(), recovered=True)
            finally:
                crashed_page.remove_listener("crash", observed_crash)
                try:
                    await session.detach()
                except PlaywrightError:
                    pass
        elif name == "backend_crash":
            before = self.tree.sample()["backend_pid"]
            owner = next(p for p in self.tree.living() if p.pid == before)
            for process in reversed([owner, *owner.children(recursive=True)]):
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    pass
            result.update(
                before_pid=before,
                after_pid=(await self.ready_again(previous_backend=before))["backend_pid"],
                recovered=True,
            )
        elif name == "desktop_restart":
            before = self.child.pid
            await self.quit()
            await self.launch()
            await self.ready_again()
            result.update(before_pid=before, after_pid=self.child.pid, recovered=True)
        elif name == "multi_window":
            opened = []
            for _ in range(2):
                before = {p for context in self.browser.contexts for p in context.pages}
                await self.page.evaluate(
                    "url => window.xcagiDesktop.openWindow(url)", self.base + "/"
                )
                other = None
                for _poll in range(150):
                    other = next(
                        (
                            p
                            for context in self.browser.contexts
                            for p in context.pages
                            if p not in before
                        ),
                        None,
                    )
                    if other is not None:
                        break
                    await asyncio.sleep(0.1)
                if other is None:
                    raise ValueError("auxiliary_window_missing")
                self.observe_page(other)
                await other.wait_for_url(self.base + "/**", timeout=60000)
                if (await other.evaluate("() => window.xcagiDesktop.getAppIdentity()")).get(
                    "isPackaged"
                ) is not True:
                    raise ValueError("auxiliary_window_unresponsive")
                opened.append(other)
            for other in opened:
                await other.close()
            result.update(
                opened=len(opened),
                remaining=sum(
                    p.url.startswith(self.base + "/")
                    for context in self.browser.contexts
                    for p in context.pages
                ),
            )
        else:
            result["remaining_processes"] = await self.quit()
        result.update(passed=True, finished_at=utc_now())
        return result


async def run(args) -> int:
    observation_errors = (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        ImportError,
        psutil.Error,
        httpx.HTTPError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
        asyncio.CancelledError,
    )
    native = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "unsupported")
    report = {
        "schema": "xcagi.desktop_soak/v1",
        "platform": native,
        "release_sha": args.release_sha,
        "product_version": args.product_version,
        "requested_duration_seconds": args.duration_seconds
        if math.isfinite(args.duration_seconds)
        else None,
        "started_at": utc_now(),
        "machine": {
            "runner_name": os.getenv("RUNNER_NAME", ""),
            "runner_environment": os.getenv("RUNNER_ENVIRONMENT", "local"),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "samples": [],
        "events": [],
        "scenarios": {},
        "blockers": [],
        "status": "running",
    }
    desktop = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("evidence_output_already_exists")
    checkpoint(args.output, report)
    try:
        if native == "unsupported":
            raise ValueError("native_windows_or_macos_required")
        if (
            not math.isfinite(args.duration_seconds)
            or not math.isfinite(args.interval_seconds)
            or args.duration_seconds < MIN_DURATION_SECONDS
            or args.duration_seconds > 86400
            or not 1 <= args.interval_seconds <= 30
            or not re.fullmatch(r"[0-9a-f]{40}", args.release_sha)
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", args.product_version)
        ):
            raise ValueError("invalid_duration_interval_or_release_sha")
        if not all(os.getenv(key) for key in ("XCAGI_TEST_USER", "XCAGI_TEST_PASS")):
            raise ValueError("dedicated_acceptance_credentials_missing")
        if not args.binary.is_file():
            raise ValueError("installed_desktop_binary_missing")
        report["artifact"], backend = artifact_identity(
            args.binary, args.release_sha, args.product_version
        )
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright

        observation_errors += (PlaywrightError,)
        async with async_playwright() as playwright:
            directory = Path(tempfile.mkdtemp(prefix="xcagi-native-soak-"))
            desktop = Desktop(args, playwright, Path(directory), backend, report)
            try:
                report["phase"] = "launch"
                await asyncio.wait_for(desktop.launch(), timeout=270)
                report["phase"] = "login"
                await asyncio.wait_for(desktop.login(), timeout=120)
                await asyncio.wait_for(desktop.identity(), timeout=20)
                if report["blockers"]:
                    raise ValueError("renderer_observation_failed")
                started = time.monotonic()
                report["phase"] = "steady"
                for sequence in range(100000):
                    view = ("settings", "chat", "customers", "products")[sequence % 4]
                    await asyncio.wait_for(
                        desktop.navigate(view),
                        timeout=30,
                    )
                    sample = desktop.tree.sample()
                    sample.update(
                        elapsed_seconds=time.monotonic() - started,
                        timestamp_utc=utc_now(),
                        endpoints=probe(desktop.client, args.release_sha),
                        gui=True,
                        gui_view=view,
                    )
                    report["samples"].append(sample)
                    checkpoint(args.output, report)
                    if report["blockers"]:
                        raise ValueError("renderer_observation_failed")
                    if (
                        not all(sample["endpoints"].values())
                        or sample["rss_bytes"] > MAX_RSS_BYTES
                        or sample["handles"] > MAX_HANDLES
                    ):
                        raise ValueError("unhealthy_or_resource_budget_exceeded")
                    elapsed = sample["elapsed_seconds"] - report["samples"][0]["elapsed_seconds"]
                    if elapsed >= args.duration_seconds:
                        break
                    await asyncio.sleep(min(args.interval_seconds, args.duration_seconds - elapsed))
                for name in (
                    "renderer_offline",
                    "renderer_crash",
                    "backend_crash",
                    "desktop_restart",
                    "multi_window",
                    "clean_exit",
                ):
                    report["phase"] = name
                    report["scenarios"][name] = {"passed": False, "started_at": utc_now()}
                    checkpoint(args.output, report)
                    report["scenarios"][name] = await asyncio.wait_for(
                        desktop.scenario(name), timeout=300
                    )
                    checkpoint(args.output, report)
                    if report["blockers"]:
                        raise ValueError("renderer_observation_failed")
                if (
                    artifact_identity(args.binary, args.release_sha, args.product_version)[0]
                    != report["artifact"]
                ):
                    raise ValueError("installed_artifact_changed_during_measurement")
                report["status"] = "completed"
            finally:
                remaining = desktop.tree.cleanup() if desktop.tree else 0
                if remaining:
                    report["blockers"].append("cleanup_processes_remaining")
                    print(
                        "Retained private acceptance profile because processes remain:", directory
                    )
                else:
                    shutil.rmtree(directory)
                desktop.client.close()
    except observation_errors as error:
        # Playwright errors can contain filled credentials and local paths: do not publish them.
        message = (
            str(error)
            if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]+", str(error))
            else type(error).__name__
        )
        report["blockers"].append(message)
        report["status"] = "blocked" if not report["samples"] else "failed"
    report["finished_at"] = utc_now()
    if report["status"] == "completed":
        verdict = verify_platform(
            report,
            platform=native,
            release_sha=args.release_sha,
            product_version=args.product_version,
        )
        report["blockers"].extend(verdict["blockers"])
        if not verdict["passed"]:
            report["status"] = "failed"
    checkpoint(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "blockers": report["blockers"],
                "samples": len(report["samples"]),
            }
        )
    )
    return 0 if report["status"] == "completed" and not report["blockers"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--product-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=28800)
    parser.add_argument("--interval-seconds", type=float, default=30)

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
