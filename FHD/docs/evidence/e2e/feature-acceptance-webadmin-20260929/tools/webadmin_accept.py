#!/usr/bin/env python3
"""Web 管理端（自托管，web 模式）真机验收执行器。

真实性边界（不得放宽）：
  * 全部用例都在【真实浏览器】里执行（Playwright Chromium，真实鼠标/键盘事件）；
    接口断言在页面上下文里用 fetch 复核，不绕过界面直接打接口冒充界面操作。
  * 截图取自本轮浏览器渲染画面；录像为本轮 Playwright 录制的真实会话（webm）。
  * 只按产品既有的用户路径判定；产品确实不具备的行为如实记为观察项。
  * 凭据不落盘：只写 sha256 指纹前 16 位。
  * media[] 一律先写 pending_review；只有真的打开截图/看完录像后才允许手改那三项。

用法：
  python3.11 webadmin_accept.py --spec specs/<feature>.py [--base URL] [--out DIR]
产物（OUT 下）：<feature>-<platform>-run.json / <feature>-<platform>-identity.json / shot/ video/ log/
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

# 本机系统代理会把 127.0.0.1 也送进代理，导致健康检查 502 假阴性。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

DEFAULT_BASE = "http://127.0.0.1:42423"
ADMIN_USER = os.environ.get("XCAGI_ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("XCAGI_ADMIN_PASS", "admin123")
REPO_ROOT = Path(__file__).resolve().parents[6]

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    LOG_LINES.append(line)
    print(line, flush=True)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str | None:
    return sha256_bytes(p.read_bytes()) if p.is_file() else None


def fp(v: str) -> str:
    return sha256_bytes(v.encode())[:16]


def load_spec(path: Path):
    spec = importlib.util.spec_from_file_location("accept_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http_json(url: str, timeout: int = 10):
    # 必须绕过系统代理：本机代理会把 127.0.0.1 也送进代理导致 502 假阴性。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - probe must not abort the round
        return {"_error": str(exc)}


def sha256_dir_hash(d: Path) -> str:
    """确定性目录摘要：按相对路径排序，串接 路径+文件摘要。"""
    if not d.is_dir():
        return ""
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode("utf-8"))
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    mod = load_spec(spec_path)
    feature = mod.FEATURE
    platform = getattr(mod, "PLATFORM", "web")
    entry = getattr(mod, "ENTRY", "/admin/login")
    cases_spec = mod.CASES
    base = args.base.rstrip("/")
    out = Path(args.out).resolve() if args.out else spec_path.parent.parent / "runs" / feature
    shot_dir, video_dir, log_dir = out / "shot", out / "video", out / "log"
    for d in (shot_dir, video_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    # 本轮重跑前清掉上一轮产物，避免把历史录像/截图当成本轮证据。
    for stale in list(shot_dir.glob("*.png")) + list(video_dir.glob("*.webm")):
        stale.unlink()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log(f"feature={feature} platform={platform} base={base} out={out}")

    from playwright.sync_api import sync_playwright

    health = http_json(base + "/api/health")
    site_git_sha = str(health.get("git_sha") or "")
    site_version = str(health.get("version") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", site_git_sha):
        log(f"FATAL: backend did not report a 40-hex git_sha ({site_git_sha!r}); refusing to fabricate one.")
        return 2

    cases: list[dict] = []
    media: list[dict] = []
    observations: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1600, "height": 1000},
        )
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)

        # ---- real UI login
        page.goto(base + "/admin/login", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        page.fill("input[name=username]", ADMIN_USER)
        page.fill("input[name=password]", ADMIN_PASS)
        page.screenshot(path=str(shot_dir / "00-login-form.png"))
        page.click("button[type=submit], button:has-text('登')")
        page.wait_for_timeout(8000)
        me = page.evaluate(
            "async () => { const r = await fetch('/api/auth/me', {credentials:'include'});"
            "return {status: r.status, body: await r.json()}; }"
        )
        logged_in = bool((me.get("body") or {}).get("success"))
        log(f"login: url={page.url} me_success={logged_in} user={(me.get('body') or {}).get('data', {}).get('user', {}).get('username')}")
        observations.append(
            f"登录入口 {base}/admin/login，账号 {ADMIN_USER}（指纹 {fp(ADMIN_USER)}），"
            f"登录后 /api/auth/me success={logged_in}。"
        )
        observations.extend(getattr(mod, "EXTRA_OBSERVATIONS", []) or [])
        if not logged_in:
            log("FATAL: admin login failed; aborting round.")
            ctx.close()
            browser.close()
            return 3

        for cs in cases_spec:
            cid, title = cs["id"], cs["title"]
            try:
                observed, passed = cs["run"](page, {"base": base, "shot": shot_dir, "log": log})
            except Exception as exc:  # noqa: BLE001 - a broken case is recorded as failed, not hidden
                observed, passed = {"exception": f"{type(exc).__name__}: {exc}"}, False
            cases.append({
                "id": cid,
                "title": title,
                "input": cs["input"],
                "actions": cs["actions"],
                "expected": cs["expected"],
                "observed": json.dumps(observed, ensure_ascii=False, default=str),
                "result": "passed" if passed else "failed",
            })
            log(f"case {cid}: {'passed' if passed else 'failed'} - {title}")

        ctx.close()  # finalizes the video file
        browser.close()

    # ---- video: Playwright writes a random-named webm; rename deterministically
    vids = [v for v in video_dir.glob("*.webm") if v.stat().st_size > 0]
    video_path = None
    if vids:
        src = max(vids, key=lambda v: v.stat().st_size)
        target = video_dir / f"{feature}-{platform}-{stamp}.webm"
        if src != target:
            shutil.move(str(src), str(target))
        video_path = target
        log(f"video: {target.name} ({target.stat().st_size} bytes)")
    else:
        log("video: NOT produced by this round")

    def rel(p: Path) -> str:
        return str(p.resolve().relative_to(REPO_ROOT))

    for s in sorted(shot_dir.glob("*.png")):
        media.append({
            "feature": feature,
            "path": rel(s),
            "sha256": sha256_file(s),
            "visual_review": "pending_review",
            "visible_result": "",
            "reviewed_at": "",
        })
    if video_path:
        media.append({
            "feature": feature,
            "path": rel(video_path),
            "sha256": sha256_file(video_path),
            "visual_review": "pending_review",
            "visible_result": "",
            "reviewed_at": "",
        })

    log_file = log_dir / f"{feature}-{platform}-{stamp}.log"
    log(f"log -> {log_file}")
    log_file.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")

    identity = {
        "_comment": "Web 管理端（自托管）真机验收的站点身份/版本/SHA 侦察快照，由 tools/webadmin_accept.py 自动生成，请勿手改（DO NOT EDIT）。",
        "kind": f"{platform}-admin-identity",
        "feature": feature,
        "platform": platform,
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entry_url": base + entry,
        "site_health": {k: v for k, v in health.items() if k != "runtime"},
        "site_git_sha": site_git_sha,
        "site_version": site_version,
        "site_release_id": str(health.get("release_id") or ""),
        "admin_console_dist_sha256": sha256_dir_hash(REPO_ROOT / "FHD/templates/admin-vue-dist"),
    }
    id_path = out / f"{feature}-{platform}-identity.json"
    id_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    passed = sum(1 for c in cases if c["result"] == "passed")
    failed = sum(1 for c in cases if c["result"] == "failed")
    run = {
        "_comment": "Web 管理端真机验收记录，由 tools/webadmin_accept.py 自动生成，请勿手改（DO NOT EDIT）。仅 media[].visual_review / visible_result / reviewed_at 可在实际查看该文件后填写。",
        "kind": "feature-acceptance",
        "feature": feature,
        "platform": platform,
        "status": "passed" if failed == 0 and passed == len(cases) and cases else "failed",
        "verdict": "PASS" if failed == 0 and passed == len(cases) and cases else "FAIL",
        "round": stamp,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_git_sha": site_git_sha,
        "app_version": site_version,
        "verified_at": date.today().isoformat(),
        "reviewed_at": "",
        "passed": passed,
        "failed": failed,
        "operator_observations": observations,
        "visible_content": getattr(mod, "VISIBLE_CONTENT", ""),
        "app_identity": {
            "entry_url": identity["entry_url"],
            "site_health": identity["site_health"],
            "admin_console_dist_sha256": identity["admin_console_dist_sha256"],
            "identity_capture": rel(id_path),
        },
        "media": media,
        "cases": cases,
    }
    run_path = out / f"{feature}-{platform}-run.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"record: {run_path} status={run['status']} passed={passed} failed={failed} media={len(media)}")
    print(json.dumps({"feature": feature, "status": run["status"], "passed": passed,
                      "failed": failed, "run": str(run_path), "identity": str(id_path),
                      "video": str(video_path) if video_path else None}, ensure_ascii=False))
    return 0 if run["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())