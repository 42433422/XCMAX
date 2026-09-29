#!/usr/bin/env python3
"""把 draft-run.json + 人工目检结论（reviews.json）落成正式 acceptance，并回写能力目录 macOS 资产。

用法：python3 acc_finalize.py [fid ...]   （缺省处理 reviews.json 中全部条目）
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import acc_core as core

HERE = Path(__file__).resolve().parent
REPO = core.REPO
ROUND = core.OUT
REL = lambda p: p.resolve().relative_to(REPO).as_posix()  # noqa: E731
CATALOG = REPO / "成都修茈科技有限公司/data/capabilities/catalog.json"
DAY = os.environ.get("XCAGI_ACCEPT_DAY", "2026-09-29")
SKIP = {"base-login"}  # 保留 2026-09-22 的完整 GUI 登录/退出验收
GATE = Path(os.environ.get("XCAGI_ACCEPT_GATE", "/Users/Shared/XCAGI-FULLCLOSED-20260928/evidence"))
IDENTITY = ROUND / "identity" / "macos-install-identity.json"
ARTIFACT = ROUND / "identity" / "macos-dmg-artifact.json"
REVIEWS = Path(os.environ.get("XCAGI_ACCEPT_REVIEWS", "")) if os.environ.get("XCAGI_ACCEPT_REVIEWS") else (
    ROUND / "reviews.json" if os.environ.get("XCAGI_ACCEPT_REL") else HERE / "reviews.json")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def ensure_identity():
    IDENTITY.parent.mkdir(parents=True, exist_ok=True)
    for src, dst in ((GATE / "gate-install.json", IDENTITY), (GATE / "gate-dmg-verify.json", ARTIFACT)):
        if not dst.is_file():
            shutil.copyfile(src, dst)


def build_run(fid: str, review: dict) -> tuple[Path, dict]:
    draft = json.loads((ROUND / fid / "draft-run.json").read_text(encoding="utf-8"))
    cases = [{k: c[k] for k in ("id", "input", "actions", "expected", "observed", "result")} for c in draft["cases"]]
    blocked = draft["status"] == "blocked"
    passed = 0 if blocked else sum(c["result"] == "passed" for c in cases)
    failed = 0 if blocked else sum(c["result"] == "failed" for c in cases)
    media = []
    for m in draft["media"]:
        tag = Path(m["path"]).stem
        if not review.get(tag):
            raise SystemExit(f"{fid}: 缺少 {tag} 的目检结论")
        media.append({"feature": fid, "path": m["path"], "sha256": sha(REPO / m["path"]),
                      "visual_review": "accepted", "visible_result": review[tag], "reviewed_at": DAY})
    log = REPO / draft["log"]["path"]
    run = {
        "_comment": f"{DAY} macOS 已安装 XCAGI.app 实机验收（CDP 驱动界面 + 同会话接口读写 + 界面读回）；原图与录屏逐项人工目检。账号仅记录用户名。",
        "kind": "feature-acceptance", "feature": fid, "platform": "macos", "round": ROUND.name,
        "status": draft["status"], "verdict": "BLOCKED" if blocked else ("FAIL" if failed else "PASS"),
        "app_git_sha": draft["app_git_sha"], "app_version": draft["app_version"],
        "account": draft.get("account") or core.accept_account(),
        "method": draft.get("method") or (
            f"经 CDP({core.CDP}) 驱动已安装的 {core.APP_PATH}：界面导航、键入与点击 + 页面内同会话 API 调用 + 界面读回；CDP screencast 录屏转 VP8 webm。"),
        "verified_at": DAY, "reviewed_at": DAY,
        "passed": passed, "failed": failed, "visible_content": review["summary"],
        "cases": cases, "media": media,
        "log": {"path": REL(log), "sha256": sha(log), "bytes": log.stat().st_size},
    }
    return ROUND / fid / f"{fid}-macos-run.json", run


def write_review(fid: str, run: dict, review: dict) -> Path:
    p = ROUND / fid / f"{fid}-macos-visual-review.json"
    shot = next((m for m in run["media"] if m["path"].endswith(".png")), run["media"][0])
    p.write_text(dumps({
        "_comment": f"{DAY} macOS 原图与录屏逐项人工复核记录；哈希与同目录 macos-run.json 的 media 一致。",
        "kind": "visual-review", "feature": fid, "platform": "macos", "reviewed_at": DAY,
        "app_version": run["app_version"], "app_git_sha": run["app_git_sha"],
        "screenshot_sha256": shot["sha256"], "visible_content": review["summary"],
        "videos": [m["path"] for m in run["media"] if m["path"].endswith((".webm", ".mp4"))],
        "full_feature_acceptance": run["status"] == "passed", "source": shot["path"],
    }), encoding="utf-8")
    return p


def is_old_macos(path: str) -> bool:
    return ("/macos/" in path or "macos-" in path or "-macos" in path) and ROUND.name not in path


def update_evidence(ev: dict, run_path: Path, run: dict, review_path: Path) -> dict:
    rel_run = REL(run_path)
    new_media = [m["path"] for m in run["media"]]
    ev = dict(ev)
    if not ev.get("review") or is_old_macos(ev.get("review", "")):
        ev["review"] = REL(review_path)
    for key, add in (("runs", [rel_run]), ("screenshots", [p for p in new_media if p.endswith(".png")]),
                     ("videos", [p for p in new_media if not p.endswith(".png")]),
                     ("logs", [run["log"]["path"]]), ("raw", [REL(IDENTITY)])):
        kept = [p for p in ev.get(key, []) if not is_old_macos(p) and p not in add]
        ev[key] = kept + add
    assets = dict(ev.get("platform_assets") or {})
    assets["macos"] = {
        "acceptance": {"path": rel_run, "sha256": sha(run_path), "required_case_ids": [c["id"] for c in run["cases"]]},
        "logs": [{"path": run["log"]["path"], "sha256": run["log"]["sha256"]}],
        "raw": [REL(IDENTITY)],
        "identity": {"path": REL(IDENTITY), "git_sha": "build_info|gitSha", "version": "build_info|version"},
        "artifact": {"path": REL(ARTIFACT), "sha256": "dmg_sha256", "git_sha": "expected_git_sha", "version": "expected_version"},
    }
    ev["platform_assets"] = assets
    return ev


def patch_catalog(updates: dict[str, callable]):
    text = CATALOG.read_text(encoding="utf-8")
    dec = json.JSONDecoder()
    for fid, fn in updates.items():
        start = None
        for pat in (f'"id": "{fid}"', f'"id":"{fid}"'):
            if pat in text:
                start = text.index(pat)
                break
        if start is None:
            raise SystemExit(f"catalog 中找不到 {fid}")
        k = text.index('"evidence"', start)
        brace = text.index("{", k)
        ev, end = dec.raw_decode(text, brace)
        new = json.dumps(fn(ev), ensure_ascii=False, separators=(", ", ": "))
        text = text[:brace] + new + text[end:]
    json.loads(text)
    CATALOG.write_text(text, encoding="utf-8")


def main(ids: list[str]):
    reviews = json.loads(REVIEWS.read_text(encoding="utf-8"))
    ensure_identity()
    updates = {}
    for fid in ids or sorted(reviews):
        if fid in SKIP:
            continue
        run_path, run = build_run(fid, reviews[fid])
        run_path.write_text(dumps(run), encoding="utf-8")
        review_path = write_review(fid, run, reviews[fid])
        updates[fid] = (lambda rp, r, vp: lambda ev: update_evidence(ev, rp, r, vp))(run_path, run, review_path)
        print(f"{fid}: {run['status']} {run['passed']}/{len(run['cases'])}")
    patch_catalog(updates)


if __name__ == "__main__":
    main(sys.argv[1:])
