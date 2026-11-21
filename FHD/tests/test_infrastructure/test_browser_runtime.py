"""Real Chromium contracts; CI must set XCMAX_BROWSER_REQUIRE_REAL=1.

No fake page or locator can satisfy these tests: receipts are counted by HTTP,
downloads are inspected on disk, and a second origin detects leaked requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.infrastructure.browser.runtime import execute_browser_plan


@pytest.fixture(scope="module", autouse=True)
def playwright_runtime():
    try:
        return importlib.import_module("playwright.async_api")
    except ImportError:
        if os.getenv("XCMAX_BROWSER_REQUIRE_REAL") == "1":
            pytest.fail("Required Playwright runtime is not installed")
        pytest.skip("Real Playwright runtime not installed; not acceptance evidence")


@pytest.fixture(scope="module")
def browser_executable(playwright_runtime):
    playwright = playwright_runtime
    executable = os.getenv("XCMAX_BROWSER_TEST_EXECUTABLE") or shutil.which("chromium")

    async def probe():
        async with playwright.async_playwright() as driver:
            browser = await driver.chromium.launch(
                executable_path=executable,
                headless=True,
                chromium_sandbox=True,
            )
            await browser.close()

    try:
        asyncio.run(probe())
    except playwright.Error:
        if os.getenv("XCMAX_BROWSER_REQUIRE_REAL") == "1":
            pytest.fail("Required real Chromium cannot start with its sandbox enabled")
        pytest.skip("Real Chromium unavailable in this environment; not acceptance evidence")
    return executable


@pytest.fixture
def website():
    state = {"submissions": [], "requests": [], "other": "", "submitted": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, body, *, status=200, content_type="text/html", headers=None):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            state["requests"].append(self.path)
            if self.path == "/redirect":
                return self.send(
                    "", status=302, headers={"Location": state["other"] + "/forbidden"}
                )
            if self.path == "/external":
                return self.send(f'<script src="{state["other"]}/forbidden"></script><p>ready</p>')
            if self.path == "/observe-post":
                return self.send("""<p>ready</p><script>
                fetch('/submit',{method:'POST',body:'{}'}).catch(()=>{});
                </script>""")
            if self.path == "/cookies/set":
                return self.send(
                    '<p id="state">stored</p>', headers={"Set-Cookie": "tenant=alice; Path=/"}
                )
            if self.path == "/cookies/read":
                return self.send(f'<p id="state">{self.headers.get("Cookie", "empty")}</p>')
            if self.path == "/report":
                body = json.dumps(state["submissions"][-1]).encode()
                return self.send(
                    body,
                    content_type="application/json",
                    headers={
                        "Content-Disposition": 'attachment; filename="../../report.json"',
                    },
                )
            if self.path == "/duplicate":
                return self.send("<button>Submit</button><button>Submit</button>")
            if self.path == "/prefilled":
                return self.send("""<label>API token <input value="token-secret-123"></label>
                    <label>Notes <textarea>textarea-secret-one\ntextarea-secret-two</textarea></label>
                    <div contenteditable="true" aria-label="Rich notes">
                        <p>rich-secret-one</p><strong>rich-secret-two</strong>
                    </div>
                    <select aria-label="Profile"><option value="profile-secret" selected>
                        private-profile-name</option></select>
                    <p>public page description</p><button>Continue</button>""")
            if self.path == "/privacy-limit":
                return self.send('<input value="over-limit-secret">' * 501)
            if self.path == "/embedded-private-form":
                return self.send("""<!doctype html><body style="margin:0;background:white">
                    <input value="top-level-secret" style="position:absolute;left:40px;top:20px;
                        width:320px;height:24px;box-sizing:border-box;border:0">
                    <iframe id="private-frame" title="Private form" src="/prefilled"
                        style="position:absolute;left:40px;top:60px;width:320px;height:140px;
                        border:0"></iframe></body>""")
            self.send("""<!doctype html><html><body>
                <label>Name <input id="name"></label>
                <label>Plan <select id="plan"><option value="normal">Normal</option>
                    <option value="pro">Pro</option></select></label>
                <label>Accept <input id="terms" type="checkbox"></label>
                <label>Evidence <input id="upload" type="file"></label><p id="filename"></p>
                <label>Command <input id="command"></label><p id="key"></p>
                <button id="submit">Submit</button><p id="receipt"></p>
                <a href="/report" download>Download report</a>
                <script>
                document.querySelector('#upload').onchange = e => {
                    document.querySelector('#filename').textContent = e.target.files[0].name;
                };
                document.querySelector('#command').onkeydown = e => {
                    document.querySelector('#key').textContent = e.key;
                };
                document.querySelector('#submit').onclick = async () => {
                    const body = {name: document.querySelector('#name').value,
                        plan: document.querySelector('#plan').value,
                        accepted: document.querySelector('#terms').checked,
                        filename: document.querySelector('#filename').textContent};
                    const response = await fetch('/submit', {method:'POST', body:JSON.stringify(body)});
                    const receipt = await response.json();
                    document.querySelector('#receipt').textContent = receipt.id + ':' + body.name;
                };
                </script></body></html>""")

        def do_POST(self):
            state["requests"].append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["submissions"].append(body)
            state["submitted"].set()
            self.send(
                json.dumps({"id": f"receipt-{len(state['submissions'])}"}),
                content_type="application/json",
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run(plan, tmp_path, origin, executable, seconds=10):
    result = asyncio.run(
        execute_browser_plan(
            plan,
            artifact_dir=tmp_path,
            allowed_origins=frozenset({origin}),
            executable_path=executable,
            deadline_monotonic=time.monotonic() + seconds,
        )
    )
    if not result["success"]:
        # Synthetic fixtures only: preserve the failing action instead of pytest's
        # abbreviated dictionary repr, without exposing production exception text.
        print(json.dumps(result, indent=2))
    return result


def text_check(selector, expected):
    return {"kind": "text", "locator": {"selector": selector}, "expected": expected}


@pytest.mark.parametrize(
    "plan,code",
    [
        ({"url": "http://localhost", "steps": []}, "invalid_browser_plan"),
        ({"url": "file:///etc/passwd", "observe": True}, "browser_policy_denied"),
        ({"url": "data:text/html,secret", "observe": True}, "browser_policy_denied"),
        ({"url": "http://localhost.evil", "observe": True}, "browser_policy_denied"),
        ({"url": "http://user:password@localhost", "observe": True}, "browser_policy_denied"),
        (
            {
                "url": "http://localhost",
                "observe": True,
                "steps": [{"action": "click", "locator": {"text": "Submit"}}],
            },
            "invalid_browser_plan",
        ),
        (
            {
                "url": "http://localhost",
                "verify": [text_check("p", "ok")],
                "steps": [
                    {"action": "upload", "locator": {"selector": "input"}, "files": ["/etc/passwd"]}
                ],
            },
            "invalid_browser_plan",
        ),
    ],
)
def test_rejected_before_browser_launch(plan, code, tmp_path):
    result = run(plan, tmp_path, "http://localhost", None)
    assert result["error_code"] == code
    assert result["outcome"] == "failed"
    assert not result["success"] and not result["verified"]


def test_form_receipt_upload_and_durable_download(website, browser_executable, tmp_path):
    origin, state = website
    result = run(
        {
            "url": origin,
            "screenshot": True,
            "steps": [
                {"action": "fill", "locator": {"label": "Name"}, "value": "Alice"},
                {"action": "select", "locator": {"label": "Plan"}, "value": "pro"},
                {"action": "check", "locator": {"label": "Accept"}, "value": True},
                {
                    "action": "upload",
                    "locator": {"label": "Evidence"},
                    "files": [
                        {"name": "proof.txt", "mime_type": "text/plain", "buffer": b"evidence"},
                    ],
                },
                {"action": "press", "locator": {"label": "Command"}, "value": "Enter"},
                {
                    "action": "click",
                    "locator": {"role": "button", "name": "Submit"},
                    "verify": [text_check("#receipt", "receipt-1:Alice")],
                },
                {"action": "download", "locator": {"role": "link", "name": "Download report"}},
            ],
            "verify": [
                text_check("#receipt", "receipt-1:Alice"),
                text_check("#key", "Enter"),
                {"kind": "value", "locator": {"label": "Name"}, "expected": "Alice"},
                {"kind": "visible", "locator": {"selector": "#receipt"}, "expected": "true"},
            ],
        },
        tmp_path,
        origin,
        browser_executable,
    )
    assert result["success"] and result["verified"], result
    assert result["outcome"] == "succeeded"
    assert state["submissions"] == [
        {"name": "Alice", "plan": "pro", "accepted": True, "filename": "proof.txt"}
    ]
    assert len(result["steps"]) == 7
    assert all(step["status"] == "completed" for step in result["steps"])
    download = next(item for item in result["artifacts"] if item["name"].endswith(".json"))
    path = Path(download["path"])
    assert path.parent == tmp_path
    assert json.loads(path.read_bytes()) == state["submissions"][0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == download["sha256"]
    assert any(item["mime_type"] == "image/png" for item in result["artifacts"])


def test_failed_postcondition_is_uncertain_and_never_replays(website, browser_executable, tmp_path):
    origin, state = website
    result = run(
        {
            "url": origin,
            "steps": [
                {"action": "click", "locator": {"role": "button", "name": "Submit"}},
            ],
            "verify": [text_check("#receipt", "wrong-receipt")],
        },
        tmp_path,
        origin,
        browser_executable,
        seconds=3,
    )
    assert len(state["submissions"]) == 1
    assert not result["success"] and not result["verified"]
    assert result["outcome"] == "unknown" and result["reconciliation_required"]
    assert not result["retryable"]


def test_context_isolation_between_runs(website, browser_executable, tmp_path):
    origin, _ = website
    first = run(
        {"url": origin + "/cookies/set", "verify": [text_check("#state", "stored")]},
        tmp_path / "a",
        origin,
        browser_executable,
    )
    second = run(
        {"url": origin + "/cookies/read", "verify": [text_check("#state", "empty")]},
        tmp_path / "b",
        origin,
        browser_executable,
    )
    assert first["verified"] and second["verified"], (first, second)


def test_screenshot_masks_embedded_frame_rectangle(website, browser_executable, tmp_path):
    from PIL import Image

    origin, _ = website
    result = run(
        {
            "url": origin + "/embedded-private-form",
            "screenshot": True,
            "verify": [
                {
                    "kind": "value",
                    "frame": "#private-frame",
                    "locator": {"label": "API token"},
                    "expected": "token-secret-123",
                }
            ],
        },
        tmp_path,
        origin,
        browser_executable,
    )
    assert result["success"] and result["verified"], result
    screenshot = next(item for item in result["artifacts"] if item["mime_type"] == "image/png")
    with Image.open(screenshot["path"]) as image:
        pixels = image.convert("RGB")
        # Fixed CSS rectangles are fully covered, including all child-frame content.
        for rectangle in ((40, 20, 360, 44), (40, 60, 360, 200)):
            crop = pixels.crop(rectangle)
            assert crop.getcolors(maxcolors=2) == [(crop.width * crop.height, (255, 0, 255))]
        assert pixels.getpixel((20, 80)) == (255, 255, 255)


def test_browser_executes_under_default_tool_worker_resource_limits(
    website, browser_executable, tmp_path
):
    origin, state = website
    script = """import asyncio, json, resource, sys, time
from pathlib import Path
from app.application.agent_orchestrator.tool_process import _apply_resource_limits
from app.infrastructure.browser.runtime import execute_browser_plan
settings = json.loads(sys.argv[1])
_apply_resource_limits()
limits = {name: resource.getrlimit(getattr(resource, name))[0]
          for name in ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NOFILE")}
print(json.dumps({"limits": limits}), flush=True)
result = asyncio.run(execute_browser_plan(
    {"url": settings["origin"], "steps": [
        {"action": "fill", "locator": {"label": "Name"}, "value": "Limited"},
        {"action": "click", "locator": {"selector": "#submit"}}],
     "verify": [{"kind": "text", "locator": {"selector": "#receipt"},
                 "expected": "receipt-1:Limited"}]},
    artifact_dir=Path(settings["artifact_dir"]),
    allowed_origins=frozenset({settings["origin"]}),
    executable_path=settings["executable"], deadline_monotonic=time.monotonic() + 12))
print(json.dumps({"result": result}), flush=True)
"""
    environment = dict(os.environ)
    # The child runs only synthetic local pages; browser launch diagnostics reveal
    # resource reservation failures without recording page bodies or form values.
    environment["DEBUG"] = "pw:browser"
    # Exercise production defaults regardless of a developer shell's overrides.
    for key in (
        "XCAGI_TOOL_SANDBOX",
        "XCAGI_TOOL_CPU_SECONDS",
        "XCAGI_TOOL_MEMORY_MB",
        "XCAGI_TOOL_MAX_FILES",
    ):
        environment.pop(key, None)
    settings = {"origin": origin, "artifact_dir": str(tmp_path), "executable": browser_executable}
    with subprocess.Popen(
        [sys.executable, "-c", script, json.dumps(settings)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=20)
        finally:
            # A failed browser launch must not leave its driver/children running.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    print(stdout)
    print(stderr)
    assert process.returncode == 0, (stdout, stderr[-4000:])
    records = [json.loads(line) for line in stdout.splitlines()]
    assert records[0]["limits"] == {
        "RLIMIT_CPU": 60,
        "RLIMIT_AS": 2048 * 1024 * 1024,
        "RLIMIT_NOFILE": 256,
    }
    result = records[-1]["result"]
    assert result["success"] and result["verified"], (result, stderr[-4000:])
    assert len(state["submissions"]) == 1 and state["submissions"][0]["name"] == "Limited"


@pytest.mark.parametrize("path", ["/redirect", "/external", "/observe-post"])
def test_network_policy_covers_redirect_resources_and_observation_writes(
    path,
    website,
    browser_executable,
    tmp_path,
):
    origin, state = website
    # The second origin has a reachable server; a denied request must never reach it.
    foreign_requests = []

    class Foreign(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            foreign_requests.append(self.path)
            self.send_response(200)
            self.end_headers()

    foreign = ThreadingHTTPServer(("127.0.0.1", 0), Foreign)
    thread = threading.Thread(target=foreign.serve_forever, daemon=True)
    thread.start()
    try:
        state["other"] = f"http://127.0.0.1:{foreign.server_port}"
        result = run({"url": origin + path, "observe": True}, tmp_path, origin, browser_executable)
        assert not result["success"]
        assert result["error_code"] == "browser_policy_denied"
        assert not foreign_requests and not state["submissions"]
    finally:
        foreign.shutdown()
        foreign.server_close()
        thread.join(timeout=2)


def test_timeout_stops_following_actions(website, browser_executable, tmp_path):
    origin, state = website
    result = run(
        {
            "url": origin,
            "steps": [
                {"action": "click", "locator": {"selector": "#missing"}},
                {"action": "click", "locator": {"selector": "#submit"}},
            ],
            "verify": [text_check("#receipt", "receipt-1:")],
        },
        tmp_path,
        origin,
        browser_executable,
        seconds=3,
    )
    assert result["error_code"] == "browser_timeout"
    assert result["outcome"] == "unknown"
    assert len(result["steps"]) == 1 and not state["submissions"]


def test_step_verification_prevents_following_write(website, browser_executable, tmp_path):
    origin, state = website
    result = run(
        {
            "url": origin,
            "steps": [
                {
                    "action": "click",
                    "locator": {"selector": "#submit"},
                    "verify": [text_check("#receipt", "wrong-receipt")],
                },
                {"action": "click", "locator": {"selector": "#submit"}},
            ],
            "verify": [text_check("#receipt", "receipt-2:")],
        },
        tmp_path,
        origin,
        browser_executable,
        seconds=3,
    )
    assert len(state["submissions"]) == 1
    assert result["outcome"] == "unknown" and len(result["steps"]) == 1


def test_lost_claim_stops_write_after_earlier_action(website, browser_executable, tmp_path):
    origin, state = website
    claims = []

    def check_claim():
        claims.append(True)
        if len(claims) > 1:
            raise RuntimeError("worker lease lost")

    result = asyncio.run(
        execute_browser_plan(
            {
                "url": origin,
                "steps": [
                    {"action": "fill", "locator": {"label": "Name"}, "value": "Alice"},
                    {"action": "click", "locator": {"selector": "#submit"}},
                ],
                "verify": [text_check("#receipt", "receipt-1:Alice")],
            },
            artifact_dir=tmp_path,
            allowed_origins=frozenset({origin}),
            executable_path=browser_executable,
            deadline_monotonic=time.monotonic() + 10,
            before_action=check_claim,
        )
    )
    assert len(claims) == 2 and not state["submissions"]
    assert not result["success"] and result["reconciliation_required"]
    assert result["outcome"] == "unknown"


def test_strict_locator_never_chooses_first_match(website, browser_executable, tmp_path):
    origin, _ = website
    result = run(
        {
            "url": origin + "/duplicate",
            "steps": [
                {"action": "click", "locator": {"role": "button", "name": "Submit"}},
            ],
            "verify": [text_check("body", "done")],
        },
        tmp_path,
        origin,
        browser_executable,
    )
    assert not result["success"] and result["outcome"] == "unknown"
    assert result["error_code"] == "browser_execution_failed"


def test_observation_redacts_prefilled_form_and_contenteditable_values(
    website, browser_executable, tmp_path
):
    origin, _ = website
    result = run(
        {"url": origin + "/prefilled", "observe": True}, tmp_path, origin, browser_executable
    )
    assert result["success"] and result["form_values_redacted"], result
    snapshot = result["snapshot"]
    for value in (
        "token-secret-123",
        "textarea-secret-one",
        "textarea-secret-two",
        "rich-secret-one",
        "rich-secret-two",
        "profile-secret",
        "private-profile-name",
    ):
        assert value not in snapshot
    assert 'textbox "API token"' in snapshot and 'textbox "Notes"' in snapshot
    assert 'button "Continue"' in snapshot and "public page description" in snapshot


def test_observation_returns_no_snapshot_when_control_inspection_exceeds_bound(
    website, browser_executable, tmp_path
):
    origin, _ = website
    result = run(
        {"url": origin + "/privacy-limit", "observe": True}, tmp_path, origin, browser_executable
    )
    assert not result["success"] and "snapshot" not in result
    assert "over-limit-secret" not in json.dumps(result)
