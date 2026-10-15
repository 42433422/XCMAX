#!/usr/bin/env python3
"""CDP 驱动：连到 XCAGI.app 渲染进程（--remote-debugging-port=9222）。

用法:
  python3 cdp_driver.py dom                 # 列出可见按钮/角标文本
  python3 cdp_driver.py click <子串>        # 点击第一个含该子串的可见按钮/元素（真实 DOM click）
  python3 cdp_driver.py eval '<js 表达式>'  # 在渲染进程求值（awaitPromise）
  python3 cdp_driver.py shot <out.png>      # 截图
  python3 cdp_driver.py status              # 打印 window.xcagiDesktop 更新状态
"""
import asyncio, base64, json, os, sys, urllib.request

# 本机 HTTP/SOCKS 代理会拦截 127.0.0.1（历史假阴性根因），必须在导入 websockets 前清掉。
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)

import websockets

CDP_HTTP = "http://127.0.0.1:9222"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def pick_page():
    raw = json.load(_OPENER.open(CDP_HTTP + "/json", timeout=10))
    pages = [t for t in raw if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    for p in pages:
        if "devtools" in (p.get("url") or ""):
            continue
        return p
    if pages:
        return pages[0]
    raise SystemExit("no page target")


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def send(self, method, params=None):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        # 单次请求最多泵 1000 条消息、单条最多等 30s，避免服务端异常时无限阻塞。
        for _ in range(1000):
            try:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                raise SystemExit(f"CDP timeout waiting for id={mid}")
            if msg.get("id") == mid:
                if "error" in msg:
                    raise SystemExit(f"CDP error: {msg['error']}")
                return msg.get("result", {})
        raise SystemExit(f"CDP no response for id={mid}")

    async def evaluate(self, expr):
        r = await self.send(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": True, "returnByValue": True},
        )
        res = r.get("result", {})
        if res.get("subtype") == "error":
            return {"error": res.get("description")}
        return res.get("value")


DOM_HELPERS = r"""
(() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  window.__xcagi_btns = () => Array.from(document.querySelectorAll('button,[role=button],.desktop-update-chip'))
    .filter(vis)
    .map((el, i) => ({ i, text: (el.innerText || el.textContent || '').trim().slice(0, 80),
                       cls: el.className && String(el.className).slice(0, 60),
                       disabled: !!el.disabled }));
  window.__xcagi_click = (sub) => {
    const els = Array.from(document.querySelectorAll('button,[role=button],.desktop-update-chip')).filter(vis);
    const hit = els.find((el) => ((el.innerText || el.textContent || '').includes(sub)));
    if (!hit) return { clicked: false, available: els.map((e) => (e.innerText || '').trim().slice(0, 60)) };
    if (hit.disabled) return { clicked: false, disabled: true, text: (hit.innerText || '').trim() };
    hit.click();
    return { clicked: true, text: (hit.innerText || '').trim().slice(0, 80), cls: String(hit.className).slice(0, 60) };
  };
  return true;
})()
"""


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dom"
    page = pick_page()
    print(f"# target: {page.get('title')} {page.get('url')}", file=sys.stderr)
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        c = CDP(ws)
        await c.evaluate(DOM_HELPERS)
        if cmd == "dom":
            print(json.dumps(await c.evaluate("window.__xcagi_btns()"), ensure_ascii=False))
        elif cmd == "click":
            print(json.dumps(await c.evaluate(f"window.__xcagi_click({json.dumps(sys.argv[2])})"), ensure_ascii=False))
        elif cmd == "eval":
            print(json.dumps(await c.evaluate(sys.argv[2]), ensure_ascii=False))
        elif cmd == "status":
            print(json.dumps(await c.evaluate(
                "window.xcagiDesktop && window.xcagiDesktop.getUpdateStatus ? window.xcagiDesktop.getUpdateStatus() : 'no-api'"),
                ensure_ascii=False))
        elif cmd == "cookies":
            await c.send("Network.enable")
            r = await c.send("Network.getAllCookies")
            out = [{"name": ck.get("name"), "value": ck.get("value"), "domain": ck.get("domain"),
                    "path": ck.get("path"), "httpOnly": ck.get("httpOnly")}
                   for ck in r.get("cookies", []) if "127.0.0.1" in (ck.get("domain") or "")]
            print(json.dumps(out, ensure_ascii=False))
        elif cmd == "shot":
            await c.send("Page.enable")
            r = await c.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            with open(sys.argv[2], "wb") as fh:
                fh.write(base64.b64decode(r["data"]))
            print(f"wrote {sys.argv[2]}")
        else:
            raise SystemExit(__doc__)


asyncio.run(main())