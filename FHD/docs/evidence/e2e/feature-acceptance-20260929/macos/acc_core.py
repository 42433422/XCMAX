#!/usr/bin/env python3
"""macOS 真机功能验收采集器核心（驱动已安装 /Applications/XCAGI.app，不修改产品）。

- 通过 CDP(9222) 连接已登录的渲染进程：业务请求在页面内 fetch，自动携带界面会话与 CSRF。
- 录屏：CDP Page.startScreencast 逐帧落盘，再用 Playwright 自带 ffmpeg 编码为 VP8 webm。
- 产出：能力中心 feature-acceptance 记录（cases/media/log），截图与录像带 sha256。
凭据不写进本文件（仓库为公开仓库）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)

import websocket  # noqa: E402

# 端口可用环境变量覆盖：默认仍是已安装客户端的标准端口（9222 / 17500）。
# XCAGI_* 与较早的 ACC_* 都认，便于隔离端口时同一份已安装客户端再验收。
CDP = os.environ.get("XCAGI_CDP") or os.environ.get("ACC_CDP", "http://127.0.0.1:9222")
BASE = os.environ.get("XCAGI_API_BASE") or os.environ.get("ACC_BASE", "http://127.0.0.1:17500")
FFMPEG = os.environ.get(
    "XCAGI_FFMPEG", str(Path.home() / "Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac"))
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4].parent
REPO_REL = os.environ.get("XCAGI_ACCEPT_REL", "FHD/docs/evidence/e2e/feature-acceptance-20260929")
OUT = REPO / REPO_REL
APP_PATH = Path(os.environ.get("XCAGI_APP_PATH", "/Applications/XCAGI.app"))


def accept_account() -> str:
    """运行记录里的账号用户名。密码只留在 XCAGI_TEST_PASS，不读取、不落盘。"""
    return os.environ.get("XCAGI_ACCEPT_ACCOUNT") or os.environ.get("XCAGI_TEST_USER") or ""
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Page:
    def __init__(self):
        targets = json.load(_opener.open(f"{CDP}/json/list", timeout=10))
        page = next(t for t in targets if t.get("type") == "page" and t["url"].startswith(BASE))
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180,
                                              suppress_origin=True)
        self._id = 0
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._frames: list[tuple[float, bytes]] | None = None
        self._stop = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.send("Page.enable")
        self.send("Runtime.enable")

    def _read(self):
        while not self._stop:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:  # noqa: BLE001
                return
            if msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                if self._frames is not None:
                    self._frames.append((time.time(), base64.b64decode(p["data"])))
                threading.Thread(target=self.send, args=("Page.screencastFrameAck",
                                 {"sessionId": p["sessionId"]}), daemon=True).start()
            elif "id" in msg:
                with self._lock:
                    self._pending[msg["id"]] = msg

    def send(self, method: str, params: dict | None = None, timeout: float = 180):
        with self._lock:
            self._id += 1
            idx = self._id
        self.ws.send(json.dumps({"id": idx, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if idx in self._pending:
                    return self._pending.pop(idx)
            time.sleep(0.01)
        raise TimeoutError(method)

    def js(self, expr: str, timeout: float = 180):
        m = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": True}, timeout)
        r = m.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(json.dumps(r["exceptionDetails"], ensure_ascii=False)[:600])
        return r.get("result", {}).get("value")

    def api(self, method: str, path: str, body=None, timeout: float = 180, form: dict | None = None):
        """页面内 fetch：沿用界面会话 cookie；写操作附带 CSRF 头。"""
        payload = json.dumps(body, ensure_ascii=False) if body is not None else "null"
        form_js = json.dumps(form, ensure_ascii=False) if form else "null"
        expr = f"""(async () => {{
          const m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
          const h = {{}};
          if (m) h['X-CSRF-Token'] = decodeURIComponent(m[1]);
          let body; const b = {payload}; const f = {form_js};
          if (f) {{ body = new FormData();
            for (const [k, v] of Object.entries(f)) {{
              if (v && typeof v === 'object' && v.__file) body.append(k, new Blob([Uint8Array.from(atob(v.b64), c => c.charCodeAt(0))], {{type: v.type}}), v.name);
              else body.append(k, v);
            }} }}
          else if (b !== null) {{ h['Content-Type'] = 'application/json'; body = JSON.stringify(b); }}
          const t0 = performance.now();
          const r = await fetch({json.dumps(path)}, {{method: {json.dumps(method)}, headers: h, body, credentials: 'include'}});
          const text = await r.text(); let data = null;
          try {{ data = JSON.parse(text); }} catch (e) {{ data = {{_raw: text.slice(0, 800)}}; }}
          return {{status: r.status, ms: Math.round(performance.now() - t0), ctype: r.headers.get('content-type'), data}};
        }})()"""
        return self.js(expr, timeout)

    def go(self, route: str, wait: float = 2.5):
        self.js(f"""(async () => {{
          const app = document.querySelector('#app')?.__vue_app__;
          const r = app?.config?.globalProperties?.$router;
          if (r) {{ await r.push({json.dumps(route)}).catch(() => {{}}); }}
          else {{ location.hash = ''; location.assign({json.dumps(route)}); }}
          return location.pathname;
        }})()""")
        time.sleep(wait)
        return self.js("location.pathname + location.search")

    def ensure_front(self) -> bool:
        """窗口被遮挡时 Chromium 暂停 rAF，过渡动画会停在半透明帧；采集前把 App 置前并确认 rAF 可用。"""
        for _ in range(3):
            subprocess.run(["osascript", "-e", 'tell application "XCAGI" to activate'],
                           capture_output=True, timeout=10)
            time.sleep(0.6)
            try:
                self.js("new Promise(r => requestAnimationFrame(() => r(1)))", timeout=4)
                return True
            except TimeoutError:
                continue
        return False

    def fill(self, selector: str, value: str):
        """聚焦并以真实键入事件填入（CDP Input.insertText），供录屏可见。"""
        self.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)});
          el.focus(); el.select && el.select(); return !!el; }})()""")
        self.send("Input.insertText", {"text": value})

    def click(self, selector: str | None = None, text: str | None = None) -> bool:
        """按选择器或可见文本点击；返回是否找到元素。"""
        return bool(self.js(f"""(() => {{
          const sel = {json.dumps(selector)}, txt = {json.dumps(text)};
          let el = sel ? document.querySelector(sel) : null;
          if (!el && txt) el = [...document.querySelectorAll('button,a,[role=button],[role=tab],li,span,div')]
            .filter(e => e.offsetParent !== null && (e.innerText || '').trim() === txt)
            .sort((a, b) => a.children.length - b.children.length)[0];
          if (!el) return false; el.scrollIntoView({{block: 'center'}}); el.click(); return true; }})()"""))

    def wait_text(self, needle: str, timeout: float = 15) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if needle in (self.js("document.body.innerText") or ""):
                return True
            time.sleep(0.5)
        return False

    def hook_net(self):
        """在页面内挂钩 fetch/XHR，记录界面自身发出的非 2xx 请求（用于发现缺陷）。"""
        self.js("""(() => { if (window.__accHooked) { window.__accErr = []; return true; }
          window.__accHooked = true; window.__accErr = [];
          const push = (m, u, s) => { if (s >= 400 || s === 0) window.__accErr.push({m, u: String(u).slice(0, 200), s}); };
          const of = window.fetch; window.fetch = async (...a) => { try { const r = await of(...a);
            push((a[1] && a[1].method) || 'GET', a[0] && a[0].url ? a[0].url : a[0], r.status); return r; }
            catch (e) { push('GET', a[0], 0); throw e; } };
          const oo = XMLHttpRequest.prototype.open, os = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.open = function (m, u, ...r) { this.__m = m; this.__u = u; return oo.call(this, m, u, ...r); };
          XMLHttpRequest.prototype.send = function (...a) { this.addEventListener('loadend', () => push(this.__m, this.__u, this.status)); return os.apply(this, a); };
          return true; })()""")

    def net_errors(self) -> list:
        return self.js("(() => { const e = window.__accErr || []; window.__accErr = []; return e; })()") or []

    def toasts(self) -> list:
        return self.js("""[...document.querySelectorAll('.el-message--error,.el-notification,.el-message-box__message,.error-state,.el-alert--error')]
          .filter(e => e.offsetParent !== null).map(e => e.innerText.trim().slice(0, 160)).filter(Boolean)""") or []

    def text(self, limit: int = 6000) -> str:
        return (self.js("document.body.innerText") or "")[:limit]

    def shot(self, out: Path) -> Path:
        m = self.send("Page.captureScreenshot", {"format": "png"})
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(m["result"]["data"]))
        return out

    def _jpeg(self) -> bytes:
        m = self.send("Page.captureScreenshot", {"format": "jpeg", "quality": 80})
        return base64.b64decode(m["result"]["data"])

    def record_start(self):
        self._frames = [(time.time(), self._jpeg())]
        self.send("Page.startScreencast", {"format": "jpeg", "quality": 80, "maxWidth": 1440,
                                           "maxHeight": 900, "everyNthFrame": 1})

    def record_stop(self, out: Path, fps: int = 8) -> Path | None:
        self.send("Page.stopScreencast")
        time.sleep(0.2)
        last = self._jpeg()
        frames, self._frames = self._frames or [], None
        frames.append((time.time(), last))
        frames.sort(key=lambda f: f[0])
        if len(frames) < 2:
            return None
        # 按真实时间戳重采样为恒定帧率：静止画面重复上一帧，保证时长与实际操作一致。
        t0, t1 = frames[0][0], frames[-1][0] + 1.0
        seq, i = [], 0
        for k in range(int((t1 - t0) * fps)):
            t = t0 + k / fps
            while i + 1 < len(frames) and frames[i + 1][0] <= t:
                i += 1
            seq.append(frames[i][1])
        out.parent.mkdir(parents=True, exist_ok=True)
        # 该 ffmpeg 构建只有 image2pipe 解复用器且无 pipe 协议：帧拼接为临时 mjpeg 流文件再编码。
        tmp = Path(f"/tmp/acc-frames-{os.getpid()}-{out.stem}.mjpeg")
        tmp.write_bytes(b"".join(seq))
        try:
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg",
                            "-framerate", str(fps), "-i", str(tmp), "-vf", "scale=1280:-2",
                            "-c:v", "libvpx", "-b:v", "700k", "-auto-alt-ref", "0", str(out)], check=True)
        finally:
            tmp.unlink(missing_ok=True)
        return out

    def close(self):
        self._stop = True
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def identity() -> dict:
    info = json.loads((APP_PATH / "Contents/Resources/build-info.json").read_text())
    return {"app_version": info["version"], "app_git_sha": info["gitSha"], "built_at": info["builtAt"],
            "account": accept_account()}


class Feature:
    """单项能力一次验收：逐用例记录 input/actions/expected/observed 与日志。"""

    def __init__(self, page: Page, fid: str, name: str):
        self.p, self.fid, self.name = page, fid, name
        self.dir = OUT / fid / "macos"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cases: list[dict] = []
        self.media: list[dict] = []
        self.log_lines: list[str] = []
        self.idx = 0

    def log(self, msg: str):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} [{self.fid}] {msg}"
        self.log_lines.append(line)

    def case(self, input_: str, actions: str, expected: str, fn):
        self.idx += 1
        cid = f"M{self.idx}"
        try:
            ok, observed = fn()
        except Exception as exc:  # noqa: BLE001
            ok, observed = False, f"执行异常：{type(exc).__name__}: {str(exc)[:400]}"
        result = "passed" if ok else "failed"
        self.log(f"{cid} {result} :: {observed[:600]}")
        self.cases.append({"id": cid, "input": input_, "actions": actions, "expected": expected,
                           "observed": observed, "result": result})
        return ok

    def shot(self, tag: str) -> Path:
        path = self.p.shot(self.dir / f"{tag}.png")
        self.media.append({"path": path, "kind": "screenshot", "tag": tag})
        self.log(f"screenshot {path.name}")
        return path

    def rec_start(self):
        self.p.record_start()

    def rec_stop(self, tag: str = "operation"):
        path = self.p.record_stop(self.dir / f"{tag}.webm")
        if path:
            self.media.append({"path": path, "kind": "video", "tag": tag})
            self.log(f"video {path.name} bytes={path.stat().st_size}")

    def finish(self, ident: dict) -> dict:
        log_path = self.dir / "run.log"
        log_path.write_text("\n".join(self.log_lines) + "\n", encoding="utf-8")
        blocked = bool(self.cases) and all(c["observed"].startswith("受阻") for c in self.cases)
        if blocked:
            for c in self.cases:
                c["result"] = "blocked"
        passed = sum(c["result"] == "passed" for c in self.cases)
        failed = sum(c["result"] == "failed" for c in self.cases)
        status = "blocked" if blocked else "failed" if failed else "passed"
        draft = {
            "kind": "feature-acceptance", "feature": self.fid, "name": self.name, "platform": "macos",
            "status": status, "verdict": {"blocked": "BLOCKED", "failed": "FAIL", "passed": "PASS"}[status],
            "app_git_sha": ident["app_git_sha"], "app_version": ident["app_version"],
            "account": ident.get("account") or accept_account(),
            "verified_at": os.environ.get("XCAGI_ACCEPT_DAY") or time.strftime("%Y-%m-%d"),
            "passed": passed, "failed": failed,
            "cases": self.cases,
            "media": [{"feature": self.fid, "path": f"{REPO_REL}/{self.fid}/macos/{m['path'].name}",
                       "sha256": sha256(m["path"]), "kind": m["kind"], "tag": m["tag"]}
                      for m in self.media],
            "log": {"path": f"{REPO_REL}/{self.fid}/macos/run.log", "sha256": sha256(log_path),
                    "bytes": log_path.stat().st_size},
            "method": f"经 CDP({CDP}) 直连驱动已安装 {APP_PATH}：界面导航 + 页面内同会话 API 调用 + 界面读回；CDP screencast 录屏",
        }
        (OUT / self.fid / "draft-run.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
        return draft
