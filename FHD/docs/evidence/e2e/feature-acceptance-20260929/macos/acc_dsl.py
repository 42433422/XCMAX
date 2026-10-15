#!/usr/bin/env python3
"""验收用例 DSL：界面导航断言、同会话 API 断言、写入后界面读回。

每个方法生成一条完整用例（input/actions/expected/observed/result），结果由真实返回判定。
"""

from __future__ import annotations

import json
import time

import acc_core as a

ERP = "/api/mod/xcagi-erp-domain-bridge"
MARK = "MAC验收0929"


def dump(v, n: int = 240) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)[:n]


def body_ok(r: dict) -> bool:
    d = r.get("data")
    return 200 <= r["status"] < 300 and not (isinstance(d, dict) and d.get("success") is False)


def rows(d) -> list:
    """从常见响应形态中取出列表。"""
    if isinstance(d, list):
        return d
    if not isinstance(d, dict):
        return []
    for k in ("data", "items", "rows", "list", "records", "results"):
        v = d.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            inner = rows(v)
            if inner:
                return inner
    return []


class R:
    def __init__(self, p: a.Page, feat: a.Feature):
        self.p, self.F, self.ctx = p, feat, {}

    # ---- 界面 -------------------------------------------------------------
    def ui(self, route: str, needles: list[str], final: str | None = None, wait: float = 3.5,
           allow_err: tuple[str, ...] = ()) -> bool:
        target = final or route

        def fn():
            self.p.net_errors()
            got = self.p.go(route, wait=wait)
            txt = self.p.text(20000)
            errs = [e for e in self.p.net_errors() if not any(x in e["u"] for x in allow_err)]
            found = [n for n in needles if n in txt]
            miss = [n for n in needles if n not in txt]
            ok = got.split("?")[0] == target.split("?")[0] and not miss and not errs
            return ok, (f"导航后路径 {got}；命中文本 {found}；缺失 {miss}；界面请求失败 "
                        f"{[(e['s'], e['u'][:80]) for e in errs[:4]]}；页面摘录：{txt[:180].replace(chr(10), ' | ')}")

        return self.F.case(
            f"界面路由 {route}",
            f"在已登录的 XCAGI.app 窗口内经 Vue Router 导航到 {route}，等待渲染后读取页面文本，并统计该页自身发出的 HTTP 请求",
            f"停留在 {target}，页面可见 {'、'.join(needles)}，该页请求无 4xx/5xx",
            fn)

    def see(self, route: str, needle: str, what: str, wait: float = 3.5) -> bool:
        """写入后的界面读回：录屏中可见新写入的数据。"""

        label = "新写入的数据" if callable(needle) else f"「{needle}」"

        def fn():
            nonlocal needle
            if callable(needle):
                needle = str(needle())
            self.p.go(route, wait=wait)
            ok = self.p.wait_text(needle, timeout=8)
            txt = self.p.text(20000)
            i = txt.find(needle)
            around = txt[max(0, i - 60): i + 120].replace("\n", " | ") if i >= 0 else txt[:160].replace("\n", " | ")
            return ok, f"{'已' if ok else '未'}在 {route} 页面看到「{needle}」；上下文：{around}"

        return self.F.case(f"界面读回：{what}", f"导航到 {route} 并在页面文本中查找{label}",
                           f"界面列表/详情中出现{label}", fn)

    def act(self, desc: str, expected: str, js_fn, check) -> bool:
        """界面交互（点击/输入）后断言页面状态。js_fn(p) 执行操作，check(p) 返回 (ok, observed)。"""

        def fn():
            js_fn(self.p)
            return check(self.p)

        return self.F.case(f"界面操作：{desc}", desc, expected, fn)

    # ---- 接口 -------------------------------------------------------------
    def api(self, what: str, method: str, path: str, body=None, check=None, expected: str = "",
            show=None, save: str | None = None, timeout: float = 90, status: tuple = (), form: dict | None = None) -> bool:
        def fn():
            r = self.p.api(method, path, body, timeout=timeout, form=form)
            d = r["data"]
            if save:
                self.ctx[save] = d
            base = (r["status"] in status) if status else body_ok(r)
            extra = True
            if check is not None and base:
                try:
                    extra = bool(check(d))
                except Exception as exc:  # noqa: BLE001
                    extra, d = False, {"check_error": repr(exc), "data": d}
            shown = show(d) if (show and base and extra) else dump(d)
            return base and extra, f"HTTP {r['status']} {r.get('ms')}ms；{shown}"

        body_txt = f" 表单文件 {form and list(form)}" if form else ("" if body is None else f" 请求体 {dump(body, 160)}")
        return self.F.case(f"{method} {path.split('?')[0]}{body_txt}",
                           f"在 App 页面内以同一登录会话调用 {method} {path}（写操作自动附带 CSRF）：{what}",
                           expected or f"{what}：HTTP 2xx 且业务字段满足断言", fn)

    def block(self, what: str, need: str) -> bool:
        def fn():
            return False, f"受阻：{need}"
        return self.F.case(what, f"尝试执行：{what}", f"{what} 成功", fn)


def ts() -> str:
    return time.strftime("%H%M%S")
