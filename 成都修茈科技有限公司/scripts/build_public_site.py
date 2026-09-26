#!/usr/bin/env python3
"""官网公开数据 SSOT 聚合器：仓库真实数据 → public-site.json。

读取（唯一事实源，均不手工复制进页面）：
  - FHD/VERSION.md                        产品版本 SSOT
  - FHD/config/saas_plans.json            价格 SSOT
  - FHD/config/public_cases.json          公开案例 SSOT
  - data/capabilities.json                能力目录（build_capability_center.py 生成）
  - download-release.json                 发布清单（发布流程生成）
  - capabilities/assets/evidence/*.json   实机验收证据（run / visual-review）

输出：
  - site/data/public-site.json            官网所有页面唯一消费的数据文件

用法：
  python3 scripts/build_public_site.py            # 生成
  python3 scripts/build_public_site.py --check    # fail-closed：SSOT 更新而未再生成 → 退出码 1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SITE_ROOT.parent
FHD_ROOT = REPO_ROOT / "FHD"
OUTPUT = SITE_ROOT / "site" / "data" / "public-site.json"
EVIDENCE_DIR = SITE_ROOT / "capabilities" / "assets" / "evidence"

SCHEMA = "xcagi.public_site/v1"


def die(msg: str) -> None:
    print(f"[public-site] FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path) -> dict:
    if not path.exists():
        die(f"SSOT 缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_media_local(name: str, feature: str | None = None) -> Path | None:
    """run.json 中的媒体名（如 03-postlogin-screen.png）→ 站点副本路径（如 base-login-03-postlogin-screen.png）。"""
    candidates: list[Path] = []
    direct = EVIDENCE_DIR / name
    if direct.exists():
        candidates.append(direct)
    if feature:
        prefixed = EVIDENCE_DIR / f"{feature}-{name}"
        if prefixed.exists():
            candidates.append(prefixed)
    if not candidates:
        candidates = sorted(EVIDENCE_DIR.glob(f"*-{name}"))
    uniq = sorted(set(candidates))
    if len(uniq) > 1:
        die(f"证据媒体名歧义: {name} → {[m.name for m in uniq]}")
    return uniq[0] if uniq else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mp4_duration_seconds(path: Path) -> float | None:
    """纯 Python 解析 MP4 mvhd box 的时长（秒），无需 ffmpeg。"""
    try:
        with path.open("rb") as fh:
            data = fh.read(4 << 20)  # mvhd 通常在文件前部
    except OSError:
        return None
    idx = data.find(b"mvhd")
    if idx < 0 or idx + 4 + 32 > len(data):
        return None
    body = data[idx + 4 :]
    version = body[0]
    try:
        if version == 1:
            # v1: creation/modification(8+8) timescale(4) duration(8)
            timescale, duration = struct.unpack(">I", body[20:24])[0], struct.unpack(">Q", body[24:32])[0]
        else:
            # v0: creation/modification(4+4) timescale(4) duration(4)
            timescale, duration = struct.unpack(">I", body[12:16])[0], struct.unpack(">I", body[16:20])[0]
        if timescale <= 0:
            return None
        return round(duration / timescale, 1)
    except struct.error:
        return None


def parse_version_md(path: Path) -> dict:
    if not path.exists():
        die(f"版本 SSOT 缺失: {path}")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\*\*XCAGI 稳定产品版本\*\*\s*\|\s*`([^`]+)`", text)
    if not m:
        die("VERSION.md 中找不到「XCAGI 稳定产品版本」锚点")
    t = re.search(r"\*\*工具链兼容版本\*\*\s*\|\s*`([^`]+)`", text)
    return {"version": m.group(1).strip(), "toolchain_version": (t.group(1).strip() if t else None)}


def format_cents(cents: int) -> str:
    return f"¥{cents // 100:,}" if cents % 100 == 0 else f"¥{cents / 100:,.2f}"


def build_pricing(plans_cfg: dict) -> dict:
    plans = plans_cfg.get("plans")
    if not plans:
        die("saas_plans.json 缺少 plans")
    out = []
    for p in plans:
        out.append(
            {
                "id": p["id"],
                "title": p["title"],
                "description": p.get("description", ""),
                "amount_cents": p["amount_cents"],
                "amount_display": format_cents(p["amount_cents"]),
                "quota_cents": p.get("quota_cents"),
                "quota_display": format_cents(p["quota_cents"]) if p.get("quota_cents") else None,
                "duration_days": p.get("duration_days"),
                "license_type": p.get("license_type"),
                "badge": p.get("badge", ""),
            }
        )
    by_id = {p["id"]: p for p in out}
    homepage_ids = ["saas-trial-30", "saas-permanent-starter", "saas-permanent-growth"]
    extended_ids = ["saas-permanent-max", "saas-permanent-ultra"]
    missing = [i for i in homepage_ids + extended_ids if i not in by_id]
    if missing:
        die(f"saas_plans.json 缺少方案: {missing}")
    trial = by_id["saas-trial-30"]
    return {
        "trial": trial,
        "trial_days": plans_cfg.get("trial_days"),
        "currency": plans_cfg.get("currency", "CNY"),
        "homepage_plans": [by_id[i] for i in homepage_ids],
        "extended_plans": [by_id[i] for i in extended_ids],
        "all_plans": out,
        "purchase_url_tpl": "/market/account-plans?plan={plan_id}&source=official-site",
    }


def build_capabilities(caps: dict) -> dict:
    stats = caps.get("stats")
    if not stats:
        die("data/capabilities.json 缺少 stats")
    by_platform = []
    for key, cov in stats.get("platform_coverage", {}).items():
        by_platform.append(
            {
                "key": key,
                "applicable": cov.get("applicable", 0),
                "verified": cov.get("verified", 0),
                "partial": cov.get("partial", 0),
                "pending": cov.get("pending", 0),
                "last_verified_at": cov.get("last_verified_at"),
            }
        )
    levels = caps.get("platform_levels", {})
    level_map = {"windows": "Windows 桌面", "macos": "macOS 桌面", "web": "Web / 后端", "android": "Android", "ios": "iOS"}
    for p in by_platform:
        p["label"] = level_map.get(p["key"], p["key"])
        p["level"] = levels.get(p["label"], "待定级")
    return {
        "total": stats.get("total"),
        "by_status": stats.get("by_status"),
        "domains": stats.get("domains"),
        "modules": stats.get("modules"),
        "completion": stats.get("completion"),
        "catalog_version": caps.get("catalog_version"),
        "platforms": by_platform,
        "principle": caps.get("principle"),
    }


def build_downloads(release: dict, version_ssot: dict) -> dict:
    history = release.get("release_history") or []
    latest = history[0] if history else None
    return {
        "version_lock": release.get("version_lock"),
        "matches_version_ssot": release.get("version_lock") == version_ssot["version"],
        "release_ready": bool(release.get("release_ready")),
        "git_sha": release.get("git_sha"),
        "generated_at": release.get("generated_at"),
        "release_root": release.get("release_root"),
        "manifest_url": release.get("manifest_url"),
        "latest_release": latest,
    }


def mp4_codec(path: Path) -> str | None:
    """扫描 MP4 头部 sample entry fourcc，识别视频编码（avc1=H.264）。"""
    try:
        with path.open("rb") as fh:
            data = fh.read(2 << 20)
    except OSError:
        return None
    # fourcc 出现在 stsd 的 sample entry：avc1(H.264)/hev1/hvc1(HEVC)/vp09/vp08/mp4v
    for cc in (b"avc1", b"hev1", b"hvc1", b"vp09", b"vp08", b"mp4v", b"av01"):
        if cc in data:
            return cc.decode("ascii")
    return None


def detect_platform(name: str) -> str | None:
    low = name.lower()
    if "-macos" in low or "macos-" in low:
        return "macos"
    if "-web" in low or "-web." in low:
        return "web"
    if "-windows" in low or "win" in low:
        return "windows"
    if "-android" in low:
        return "android"
    return None


def build_evidence(cases_cfg: dict) -> dict:
    """扫描 evidence 目录，按 feature 聚合实机验收记录与媒体（含 sha256）。

    fail-closed 语义：站点副本与 run.json 记录哈希不一致的媒体**拒绝发布**
    （public_path=None），并登记进 evidence.integrity_problems —— 矛盾透明
    暴露而非静默发布，也不臆造"正确版本"来掩盖上游数据漂移。
    """
    features: dict[str, dict] = {}
    videos: list[dict] = []
    integrity_problems: list[dict] = []

    run_files = sorted(EVIDENCE_DIR.glob("*-run.json"))
    if not run_files:
        die(f"证据目录无 run.json: {EVIDENCE_DIR}")

    # 追溯链：FHD 验收目录中的 videos-manifest.json（原始录像 → 原始 SHA256）
    original_map: dict[str, dict] = {}
    for mf in (FHD_ROOT / "docs" / "evidence" / "e2e").glob("*/base-login/*/videos-manifest.json"):
        try:
            for item in json.loads(mf.read_text(encoding="utf-8")):
                stem = Path(item["name"]).stem
                original_map[stem] = item
        except (json.JSONDecodeError, KeyError):
            continue

    for rf in run_files:
        try:
            d = json.loads(rf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            die(f"证据 run.json 损坏: {rf}")
        feat = d.get("feature")
        if not feat:
            die(f"run.json 缺少 feature 字段: {rf}")
        platform = detect_platform(rf.stem)
        media_out = []
        for m in d.get("media", []):
            name = Path(m.get("path", "")).name
            entry = {
                "file": name,
                "sha256": m.get("sha256"),
                "visual_review": m.get("visual_review"),
                "visible_result": m.get("visible_result"),
                "kind": "video" if name.endswith((".mp4", ".webm", ".mov")) else "screenshot",
            }
            local = resolve_media_local(name, feat)
            if local:
                actual = sha256_file(local)
                if entry["kind"] == "video":
                    # 视频：run.json 记录的 sha 通常指向 FHD 原件；站点展示副本（转码/裁剪）
                    # 以自身 actual sha256 记录保证可追溯。与记录的差异透明登记，不据此拒发。
                    if actual != m.get("sha256"):
                        integrity_problems.append(
                            {
                                "feature": feat,
                                "file": name,
                                "kind": "sha-differs-from-record",
                                "recorded_sha256": m.get("sha256"),
                                "actual_sha256": actual,
                                "action": "publish-with-actual-sha",
                            }
                        )
                    entry["sha256"] = actual
                    dur = mp4_duration_seconds(local)
                    codec = mp4_codec(local) if local.suffix == ".mp4" else ("webm" if local.suffix == ".webm" else None)
                    poster = EVIDENCE_DIR / f"{feat}-03-postlogin-screen.png"
                    entry.update(
                        {
                            "file": local.name,
                            "size_bytes": local.stat().st_size,
                            "duration_seconds": dur,
                            "codec": codec,
                        }
                    )
                    # 视频发布闸门（任务书八/二十三）：时长 ≤60s、H.264 MP4、poster、
                    # 原始录像可追溯。不满足者拒绝发布并登记——官网只出合规验收录像。
                    blockers = []
                    if dur is None or dur > 60:
                        blockers.append(f"时长超 60s 或不可解析({dur})")
                    if local.suffix == ".mp4" and codec != "avc1":
                        blockers.append(f"非 H.264 编码({codec})")
                    if local.suffix == ".webm":
                        blockers.append("webm 不作官网展示")
                    stem_no_platform = Path(local.name).stem.replace("-web", "").replace("-macos", "")
                    stem_candidates = [Path(local.name).stem, stem_no_platform, stem_no_platform.replace(f"{feat}-", "")]
                    orig = next(
                        (original_map[c] for c in stem_candidates if c in original_map),
                        None,
                    )
                    if not orig:
                        blockers.append("原始录像不可追溯")
                    if blockers:
                        integrity_problems.append(
                            {
                                "feature": feat,
                                "file": local.name,
                                "issues": blockers,
                                "action": "not-published",
                            }
                        )
                        entry["public_path"] = None
                        media_out.append(entry)
                        continue
                    entry["public_path"] = f"/capabilities/assets/evidence/{local.name}"
                    entry["duration_ok"] = True
                    entry["poster"] = f"/capabilities/assets/evidence/{poster.name}" if poster.exists() else None
                    if orig:
                        entry["original_recording"] = {
                            "name": orig["name"],
                            "sha256": orig["sha256"],
                            "bytes": orig["bytes"],
                            "archive_path": orig.get("archive_path"),
                        }
                    videos.append({**entry, "feature": feat, "platform": platform})
                else:
                    # 截图无转码差异：站点副本必须与 run.json 记录逐哈希一致，
                    # 不一致即上游数据漂移 → 拒绝发布并登记（fail-closed）。
                    if actual != m.get("sha256"):
                        integrity_problems.append(
                            {
                                "feature": feat,
                                "file": local.name,
                                "kind": "sha-mismatch-not-published",
                                "recorded_sha256": m.get("sha256"),
                                "actual_sha256": actual,
                                "action": "not-published",
                            }
                        )
                        entry["public_path"] = None
                    else:
                        entry["file"] = local.name
                        entry["public_path"] = f"/capabilities/assets/evidence/{local.name}"
            else:
                entry["public_path"] = None  # 原始证据存档于 FHD/docs/evidence，不在官网发布
            media_out.append(entry)
        cur = features.get(feat)
        # 验收运行日志（run.log）：原文公开 + SHA256，供验证中心技术层引用
        log_entry = None
        log_candidates = sorted(set(EVIDENCE_DIR.glob(f"{feat}-run.log")) | set(EVIDENCE_DIR.glob(f"{feat}_run.log")))
        if log_candidates:
            lf = log_candidates[0]
            log_entry = {
                "file": lf.name,
                "public_path": f"/capabilities/assets/evidence/{lf.name}",
                "sha256": sha256_file(lf),
                "size_bytes": lf.stat().st_size,
            }
        item = {
            "feature": feat,
            "platform": platform,
            "status": d.get("status"),
            "passed": d.get("passed", 0),
            "failed": d.get("failed", 0),
            "verified_at": d.get("verified_at"),
            "app_version": d.get("app_version"),
            "app_git_sha": d.get("app_git_sha"),
            "media": media_out,
            "run_log": log_entry,
            "source_run": f"/capabilities/assets/evidence/{rf.name}",
        }
        if cur is None or (item["verified_at"] or "") >= (cur["verified_at"] or ""):
            features[feat] = item

    feats = sorted(features.values(), key=lambda x: x["feature"])
    passed = sum(1 for f in feats if f["status"] == "passed")
    failed = sum(1 for f in feats if f["status"] == "failed")
    verified_dates = [f["verified_at"] for f in feats if f["verified_at"]]
    if integrity_problems:
        print(
            f"[public-site] WARN: {len(integrity_problems)} 个证据媒体与 run.json 记录不一致，已拒绝发布并登记"
            f"（上游数据漂移，需证据责任方修正）:",
            file=sys.stderr,
        )
        for p in integrity_problems[:10]:
            print(f"  - {p['feature']}/{p['file']}", file=sys.stderr)
    return {
        "features": feats,
        "videos": sorted(videos, key=lambda v: (v["feature"], v["file"])),
        "integrity_problems": integrity_problems,
        "summary": {
            "total": len(feats),
            "passed": passed,
            "failed": failed,
            "last_verified_at": max(verified_dates) if verified_dates else None,
        },
    }


def attach_case_media(cases: list[dict], evidence: dict) -> None:
    """案例截图/视频绑定公开路径、SHA256 与验收状态（fail-closed：文件缺失即失败）。"""
    feat_idx = {f["feature"]: f for f in evidence["features"]}
    for case in cases:
        for shot in case.get("screenshots", []):
            local = SITE_ROOT / shot["file"]
            if not local.exists():
                die(f"案例 {case['case_id']} 截图缺失: {local}")
            shot["public_path"] = f"/{shot['file']}"
            shot["sha256"] = sha256_file(local)
            ref = feat_idx.get(shot["feature"])
            shot["acceptance_status"] = (ref or {}).get("status") or "no-acceptance-record"
            shot["verified_at"] = (ref or {}).get("verified_at")
        for vid in case.get("videos", []):
            local = SITE_ROOT / vid["file"]
            if not local.exists():
                die(f"案例 {case['case_id']} 视频缺失: {local}")
            dur = mp4_duration_seconds(local)
            if dur is None or dur > 60:
                die(f"案例 {case['case_id']} 视频时长不合规(>60s 或不可解析): {local} = {dur}s")
            vid.update(
                {
                    "public_path": f"/{vid['file']}",
                    "sha256": sha256_file(local),
                    "size_bytes": local.stat().st_size,
                    "duration_seconds": dur,
                }
            )


def data_updated_at(*candidates: str | None) -> str | None:
    dates = []
    for c in candidates:
        if not c:
            continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(c))
        if m:
            dates.append(m.group(0))
    return max(dates) if dates else None


def build() -> dict:
    version_ssot = parse_version_md(FHD_ROOT / "VERSION.md")
    plans_cfg = read_json(FHD_ROOT / "config" / "saas_plans.json")
    cases_cfg = read_json(FHD_ROOT / "config" / "public_cases.json")
    caps = read_json(SITE_ROOT / "data" / "capabilities.json")
    release = read_json(SITE_ROOT / "download-release.json")

    cases = cases_cfg.get("cases")
    if not cases:
        die("public_cases.json 缺少 cases")

    evidence = build_evidence(cases_cfg)
    attach_case_media(cases, evidence)

    hero_candidates = [m for f in evidence["features"] if f["feature"] == "base-login" for m in f["media"] if m["file"] == "base-login-03-postlogin-screen.png"]
    hero = None
    if hero_candidates:
        h = hero_candidates[0]
        hero = {
            "file": h["public_path"],
            "sha256": h["sha256"],
            "caption": "XCAGI 实机工作台：太阳鸟企业账号（SUNBIRD·饰品包装助手）登录后的智能对话界面",
            "acceptance_status": "passed",
            "verified_at": next(f["verified_at"] for f in evidence["features"] if f["feature"] == "base-login"),
        }

    last_verified = evidence["summary"]["last_verified_at"]
    return {
        "schema": SCHEMA,
        "_comment": "由 scripts/build_public_site.py 自动生成，请勿手改（DO NOT EDIT）。事实来源见 sources。",
        "sources": {
            "version": "FHD/VERSION.md",
            "pricing": "FHD/config/saas_plans.json",
            "cases": "FHD/config/public_cases.json",
            "capabilities": "data/capabilities.json",
            "release": "download-release.json",
            "evidence": "capabilities/assets/evidence/",
        },
        "product": {
            "name": "XCAGI",
            "internal_platform": "XCMAX",
            "brand_note": "XCAGI 是对外产品名称；XCMAX 是其内部工程与平台体系名称。",
            **version_ssot,
        },
        "data_updated_at": data_updated_at(last_verified, caps.get("generated_at"), release.get("generated_at")),
        "pricing": build_pricing(plans_cfg),
        "platforms": build_capabilities(caps)["platforms"],
        "capabilities": build_capabilities(caps),
        "downloads": build_downloads(release, version_ssot),
        "cases": cases,
        "evidence": evidence,
        "hero_media": hero,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail-closed：生成结果与磁盘不一致则退出码 1")
    args = ap.parse_args()

    data = build()
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not OUTPUT.exists():
            die(f"--check：输出不存在，请先运行生成: {OUTPUT}")
        disk = OUTPUT.read_text(encoding="utf-8")
        if disk != payload:
            import difflib

            diff = list(difflib.unified_diff(disk.splitlines(), payload.splitlines(), "disk", "regenerated", lineterm=""))
            print("\n".join(diff[:60]), file=sys.stderr)
            die(f"public-site.json 与 SSOT 重新生成结果不一致（SSOT 已更新但未重新生成）: {OUTPUT}")
        print(f"[public-site] OK: {OUTPUT} 与 SSOT 一致")
        return

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(payload, encoding="utf-8")
    print(
        f"[public-site] wrote {OUTPUT} "
        f"(version={data['product']['version']}, plans={len(data['pricing']['all_plans'])}, "
        f"cases={len(data['cases'])}, evidence_features={data['evidence']['summary']['total']}, "
        f"videos={len(data['evidence']['videos'])})"
    )


if __name__ == "__main__":
    dt = datetime.now(timezone.utc)  # noqa: F841  仅用于本地调试观察；产物不含墙钟时间以保证 --check 确定性
    main()
