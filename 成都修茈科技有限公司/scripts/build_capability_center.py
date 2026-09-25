#!/usr/bin/env python3
"""Build catalog.json pages; --check rejects drift. File presence is not acceptance."""

from __future__ import annotations

import argparse
import html
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WEBSITE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = WEBSITE_DIR / "data" / "capabilities" / "catalog.json"
OUT_DIR = WEBSITE_DIR / "capabilities"
PUBLIC_DATA_PATH = WEBSITE_DIR / "data" / "capabilities.json"
EVIDENCE_ASSET_DIR = OUT_DIR / "assets" / "evidence"

STATUS_META = {
    "verified": {"label": "已验证", "cls": "st-verified", "rank": 3},
    "partial": {"label": "部分验证", "cls": "st-partial", "rank": 2},
    "implemented": {"label": "已实现待验证", "cls": "st-implemented", "rank": 1},
    "planned": {"label": "规划中", "cls": "st-planned", "rank": 0},
    "cancelled": {"label": "已取消", "cls": "st-cancelled", "rank": -1},
}
STATUS_ORDER = ["verified", "partial", "implemented", "planned"]

PLATFORM_STATUS_META = {"verified": {"label": "已验证", "cls": "ps-verified"}, "partial": {"label": "部分验证", "cls": "ps-partial"}, "pending": {"label": "待验证", "cls": "ps-pending"}}

STATUS_LEGEND = (
    ("verified", "本项全部适用平台都通过实机验收；只有一个平台通过时只能到「部分验证」"),
    ("partial", "实现已合入，且至少一个平台已有实机验收记录，但并非全部适用平台都已通过"),
    ("implemented", "代码已合入，但尚未有任何平台的实机验收记录"),
    ("planned", "仅有设计与规划，无已合入实现"),
)

PLATFORM_META = {"windows": "Windows 桌面", "macos": "macOS 桌面", "web": "Web", "android": "Android", "ios": "iOS"}

COMPLETION_WEIGHT = {"verified": 1.0, "partial": 0.7, "implemented": 0.4, "planned": 0.0}

TICK_CLASS = {"verified": "t-ok", "partial": "t-part", "implemented": "t-wip", "planned": "t-todo"}

DOMAIN_ACCENTS = (
    "#2f6df6", "#7c4dff", "#12a150", "#ff8a00", "#e6486b",
    "#0f9d8c", "#e5484d", "#2f6df6", "#7c4dff", "#12a150",
)

# 三端产品形态：等级文案取自 FHD/VERSION.md「各端交付等级」表，不另写对外口径。
PRODUCT_FORMS = (
    {"name": "桌面端", "sub": "Windows / macOS", "keys": ("Windows 桌面", "macOS 桌面")},
    {"name": "移动端", "sub": "Android", "keys": ("Android",)},
    {"name": "管理端", "sub": "Web", "keys": ("Web / 后端",)},
)
CUSTOMER_PLATFORMS = (
    {"name": "Windows", "keys": ("Windows 桌面",)},
    {"name": "macOS", "keys": ("macOS 桌面",)},
    {"name": "Android", "keys": ("Android",)},
    {"name": "Web / 后端", "keys": ("Web / 后端",)},
)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def status_badge(status: str) -> str:
    meta = STATUS_META.get(status, {"label": status, "cls": ""})
    return f'<span class="cap-status {esc(meta["cls"])}">{esc(meta["label"])}</span>'


def catalog_payload(data: dict) -> str:
    """内嵌同一份能力目录供全景和目录页使用。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def e(path: str) -> Path:
    return REPO_ROOT / path


def path_exists(rel: str) -> bool:
    return e(rel).exists()


def evidence_asset_name(feature: str, rel: str, platform: str | None = None,
                        collisions: set[str] | None = None) -> str:
    qualified = platform and Path(rel).name in (collisions or set())
    prefix = f"{feature}-{platform}" if qualified else feature
    return f"{prefix}-{Path(rel).name}"


def public_asset_matches(feature: str, rel: str, platform: str | None = None,
                         collisions: set[str] | None = None) -> bool:
    source = e(rel)
    public = EVIDENCE_ASSET_DIR / evidence_asset_name(feature, rel, platform, collisions)
    return (source.is_file() and public.is_file()
            and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(public.read_bytes()).digest())


def platform_asset_collisions(feature: dict) -> set[str]:
    names: dict[str, set[str]] = {}
    for verdict in feature.get("verdicts", []):
        platform = verdict["id"]
        paths = [r.get("_acceptance_path") for r in verdict["runs"]]
        paths += [m.get("path") for r in verdict["runs"] for m in r.get("media", [])]
        paths += verdict.get("logs", []) + verdict.get("raw", [])
        paths += [verdict.get("identity_path"), verdict.get("artifact_path")]
        for observation in verdict.get("observations", []):
            paths += [observation.get("record_path"), observation.get("identity_path")]
            paths += [a.get("path") for a in observation.get("assets", [])]
        for path in paths:
            if path:
                names.setdefault(Path(path).name, set()).add(platform)
    return {name for name, platforms in names.items() if len(platforms) > 1}


def git(*args: str, cwd: Path = REPO_ROOT) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, timeout=30, check=True,
            encoding="utf-8", errors="replace",  # 显式 UTF-8，消除 CI/locale 差异
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def reviewed_runs(feat: dict) -> list[dict]:
    """只接受覆盖 registry 全部必需用例的完整 acceptance。"""
    accepted = []
    for rel in feat.get("evidence", {}).get("runs", []):
        try:
            raw = e(rel).read_bytes()
            run = json.loads(raw)
            cases, media = run.get("cases", []), run.get("media", [])
            profile = feat["evidence"].get("platform_assets", {}).get(run.get("platform"), {})
            acceptance = profile.get("acceptance", {})
            required_ids = acceptance.get("required_case_ids")
            case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
            blocked = run.get("status") == "blocked"
            if (run.get("kind") != "feature-acceptance" or run.get("feature") != feat["id"]
                    or run.get("status") not in {"passed", "failed", "blocked"} or not run.get("verified_at")
                    or not re.fullmatch(r"[0-9a-f]{40}", run.get("app_git_sha", ""))
                    or git("merge-base", "--is-ancestor", run["app_git_sha"], "HEAD") is None
                    or not run.get("app_version") or run.get("platform") not in feat.get("platforms", [])
                    or acceptance.get("path") != rel
                    or hashlib.sha256(raw).hexdigest() != acceptance.get("sha256")
                    or not isinstance(required_ids, list) or not required_ids
                    or (not blocked and case_ids != required_ids)
                    or any(not isinstance(case_id, str) or not case_id for case_id in required_ids)
                    or len(required_ids) != len(set(required_ids))
                    or not cases or not media or type(run.get("passed")) is not int
                    or type(run.get("failed")) is not int):
                continue
            allowed_results = {"blocked"} if blocked else {"passed", "failed"}
            if not all(c.get("result") in allowed_results and all(c.get(k) for k in
                       ("input", "actions", "expected", "observed")) for c in cases):
                continue
            passed = sum(c["result"] == "passed" for c in cases)
            failed = sum(c["result"] == "failed" for c in cases)
            if blocked:
                if run["passed"] != 0 or run["failed"] != 0 or run.get("verdict", "BLOCKED") != "BLOCKED":
                    continue
            elif (run["passed"] != passed or run["failed"] != failed
                    or run["status"] != ("failed" if failed else "passed")
                    or run.get("verdict") != ("FAIL" if failed else "PASS")):
                continue
            declared = sum((feat["evidence"].get(k, []) for k in ("screenshots", "videos")), [])
            if not all(m.get("feature") == feat["id"] and m.get("visual_review") == "accepted"
                       and m.get("visible_result") and m.get("reviewed_at") and m["path"] in declared
                       and e(m["path"]).is_file()
                       and hashlib.sha256(e(m["path"]).read_bytes()).hexdigest() == m.get("sha256") for m in media):
                continue
            run["_acceptance_path"] = rel
            run["_acceptance_sha256"] = hashlib.sha256(raw).hexdigest()
            accepted.append(run)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return accepted

def nested_value(value: dict, dotted_path: str):
    for part in dotted_path.split("|"):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def traceable_pass(feat: dict, platform: str, run: dict) -> tuple[bool, str | None]:
    assets = (feat.get("evidence", {}) or {}).get("platform_assets", {}).get(platform, {})
    try:
        accept, ident, art = assets["acceptance"], assets["identity"], assets["artifact"]
        read = lambda ref: json.loads(e(ref["path"]).read_text(encoding="utf-8"))
        identity, artifact = read(ident), read(art)
        sha = nested_value(artifact, art["sha256"])
        logs = assets.get("logs", [])
        run_log = run.get("log")
        run_log_matches = run_log is None or (isinstance(run_log, dict) and any(
            item.get("path") == run_log.get("path") and item.get("sha256") == run_log.get("sha256")
            and type(run_log.get("bytes")) is int and e(run_log["path"]).stat().st_size == run_log["bytes"]
            for item in logs))
        types = {Path(m["path"]).suffix.lower() for m in run["media"]}
        complete = (ident["path"] in assets.get("raw", [])
                    and nested_value(identity, ident["git_sha"]) == run["app_git_sha"]
                    and nested_value(identity, ident["version"]) == run["app_version"]
                    and nested_value(artifact, art["git_sha"]) == run["app_git_sha"]
                    and nested_value(artifact, art["version"]) == run["app_version"]
                    and re.fullmatch(r"[0-9a-f]{64}", str(sha or ""))
                    and types & {".png", ".jpg", ".jpeg", ".webp"} and types & {".mp4", ".webm", ".mov"}
                    and run_log_matches
                    and logs and all(e(log["path"]).is_file() and e(log["path"]).stat().st_size
                                     and hashlib.sha256(e(log["path"]).read_bytes()).hexdigest() == log["sha256"]
                                     for log in logs))
        return bool(complete), sha if complete else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False, None


def platform_verdicts(feat: dict, runs: list[dict], warnings: list[str]) -> list[dict]:
    """固定列出目录声明的平台；状态必须由本平台有效运行记录派生。"""
    applicable = feat.get("platforms", []) or []
    declared = (feat.get("evidence", {}) or {}).get("platform_assets", {}) or {}
    out = []
    for p in applicable:
        assets = declared.get(p, {}) or {}
        acceptance_path = assets.get("acceptance", {}).get("path")
        p_runs = [r for r in runs if r.get("platform") == p and r.get("_acceptance_path") == acceptance_path]
        latest = max(p_runs, key=lambda r: (r.get("verified_at", ""), r.get("round", ""), r.get("generated_at", "")), default=None)
        complete, artifact_sha = traceable_pass(feat, p, latest) if latest else (False, None)
        passed, failed = bool(latest and latest["status"] == "passed"), bool(latest and latest["status"] == "failed")
        status = "verified" if complete and passed else "partial" if failed else "pending"
        artifact_path = assets.get("artifact", {}).get("path")
        out.append({
            "id": p,
            "name": PLATFORM_META.get(p, p),
            "status": status,
            "runs": p_runs,
            "accepted": [latest] if complete and passed else [],
            "media": [m for r in p_runs for m in r.get("media", [])],
            "logs": [x["path"] for x in (assets.get("logs") or []) if path_exists(x.get("path", ""))],
            "raw": [x for x in (assets.get("raw") or []) if path_exists(x)],
            "identity_path": assets.get("identity", {}).get("path"),
            "verified_at": latest.get("verified_at") if complete and passed else None,
            "artifact_sha256": artifact_sha if complete else None,
            "artifact_path": artifact_path,
            "observations": platform_observations(feat, p, warnings),
        })
    for r in runs:
        if r.get("platform") not in applicable:
            warnings.append(
                f"[{feat['id']}] 运行记录缺少有效 platform 标注（{r.get('platform')!r}），不计入任何平台状态")
    return out


def platform_observations(feat: dict, platform: str, warnings: list[str]) -> list[dict]:
    """Read supplemental real-device records for display only; they never verify a platform."""
    declared = (feat.get("evidence", {}) or {}).get("platform_assets", {}).get(platform, {}) or {}
    out = []
    for spec in declared.get("observations", []) or []:
        record_ref = spec.get("record", {}) or {}
        record_path = record_ref.get("path", "")
        record, record_sha = {}, None
        try:
            raw = e(record_path).read_bytes()
            record_sha = hashlib.sha256(raw).hexdigest()
            if record_sha != record_ref.get("sha256"):
                warnings.append(f"ERROR [{feat['id']}/{platform}] 补充记录 SHA-256 不匹配: {record_path}")
            record = json.loads(raw)
            if (record.get("feature") != feat["id"]
                    or (record.get("platform") and record["platform"] != platform)
                    or (record.get("platforms") and platform not in record["platforms"])):
                warnings.append(f"ERROR [{feat['id']}/{platform}] 补充记录的 capability/platform 不匹配: {record_path}")
        except (OSError, ValueError, TypeError):
            warnings.append(f"[{feat['id']}/{platform}] 补充记录缺失或无法读取: {record_path}")

        identity_spec = spec.get("identity", {}) or {}
        identity_path = identity_spec.get("path", "")
        try:
            identity_raw = e(identity_path).read_bytes()
            identity = json.loads(identity_raw)
        except (OSError, ValueError, TypeError):
            identity_raw = b""
            identity = {}
            warnings.append(f"[{feat['id']}/{platform}] 补充记录的身份/交付文件缺失或无法读取: {identity_path}")
        identity_sha = hashlib.sha256(identity_raw).hexdigest() if identity_raw else None
        identity_sha_valid = bool(identity_sha and (
            not identity_spec.get("sha256") or identity_sha == identity_spec["sha256"]))
        if identity_sha and not identity_sha_valid:
            warnings.append(f"ERROR [{feat['id']}/{platform}] 身份/交付 JSON SHA-256 不匹配: {identity_path}")
        version = nested_value(identity, identity_spec.get("version", ""))
        git_sha = nested_value(identity, identity_spec.get("git_sha", ""))
        artifact_sha = nested_value(identity, identity_spec.get("artifact_sha256", ""))
        record_git_sha = record.get("app_git_sha") or record.get("git_sha")
        record_version = record.get("app_version") or record.get("product_version") or record.get("version")
        identity_traceable = bool(
            isinstance(version, str) and version and version == record_version
            and re.fullmatch(r"[0-9a-f]{40}", str(git_sha or ""))
            and git_sha == record_git_sha
            and git("merge-base", "--is-ancestor", str(git_sha), "HEAD") is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(artifact_sha or ""))
            and identity_sha_valid
        )

        assets = []
        media_by_kind = {m.get("kind"): m for m in record.get("media", []) if isinstance(m, dict)}
        for asset_spec in spec.get("assets", []) or []:
            path = asset_spec.get("path", "")
            exists = e(path).is_file()
            digest = hashlib.sha256(e(path).read_bytes()).hexdigest() if exists else None
            expected = asset_spec.get("sha256")
            bound = media_by_kind.get(asset_spec.get("kind"))
            record_path_ref = record.get(asset_spec.get("kind")) if asset_spec.get("kind") in {"screenshot", "video", "log"} else None
            path_bound = (bound.get("path") == path if bound else
                          bool(record_path_ref and path.endswith(str(record_path_ref)))
                          or bool((record.get("six_elements") or {}).get(asset_spec.get("kind"))))
            hash_bound = not bound or not bound.get("sha256") or bound.get("sha256") == expected
            if not path_bound or not hash_bound:
                warnings.append(f"ERROR [{feat['id']}/{platform}] 补充证据与来源记录未绑定: {path}")
            if exists and expected and digest != expected:
                warnings.append(f"ERROR [{feat['id']}/{platform}] 补充证据 SHA-256 不匹配: {path}")
            assets.append({**asset_spec, "exists": exists, "path_bound": path_bound and hash_bound,
                           "actual_sha256": digest,
                           "sha256_valid": bool(exists and expected and digest == expected)})
        out.append({
            "record_path": record_path,
            "record_sha256": record_sha,
            "record_sha256_valid": bool(record_sha and record_sha == record_ref.get("sha256")),
            "record_result": record.get("verdict") or record.get("status") or record.get("result") or "未记录",
            "record_note": record.get("status_basis") or record.get("visible_content") or record.get("notes") or "",
            "version": version,
            "git_sha": git_sha,
            "identity_path": identity_path,
            "identity_sha256": identity_sha,
            "identity_sha256_valid": identity_sha_valid,
            "artifact_sha256": artifact_sha,
            "identity_traceable": identity_traceable,
            "assets": assets,
        })
    return out


def aggregate_status(feat: dict, verdicts: list[dict], impl_ok: list[str]) -> str:
    """总体状态 = 平台状态 + 实现存在的纯函数；目录里不再允许手写状态。"""
    if not impl_ok:
        return "planned"
    statuses = [v["status"] for v in verdicts]
    if statuses and all(s == "verified" for s in statuses):
        return "verified"
    if any(s in ("verified", "partial") for s in statuses):
        return "partial"
    return "implemented"


def contains_key(value, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    return isinstance(value, list) and any(contains_key(item, key) for item in value)


def validate_feature(feat: dict, warnings: list[str]) -> dict:
    """校验单个功能的证据，返回最终状态与证据明细。No Evidence, No Claim。"""
    ev = feat.get("evidence", {}) or {}
    if ("status" in feat or "platform_status" in feat
            or contains_key(ev.get("platform_assets") or {}, "status")):
        raise ValueError(f"[{feat['id']}] capability and platform status must be evidence-derived")
    impl = ev.get("impl", []) or []
    tests = ev.get("tests", []) or []
    ci = ev.get("ci", []) or []
    docs = ev.get("docs", []) or []
    shots = ev.get("screenshots", []) or []
    videos = ev.get("videos", []) or []
    logs = ev.get("logs", []) or []
    raw = ev.get("raw", []) or []

    impl_ok = [p for p in impl if path_exists(p)]
    tests_ok = [p for p in tests if path_exists(p)]
    ci_ok = [p for p in ci if path_exists(p.split(":")[0])]
    docs_ok = [p for p in docs if path_exists(p)]
    shots_ok = [p for p in shots if path_exists(p)]
    videos_ok = [p for p in videos if path_exists(p)]
    logs_ok = [p for p in logs if path_exists(p)]
    raw_ok = [p for p in raw if path_exists(p)]

    for paths, present, label in ((impl, impl_ok, "实现"), (tests, tests_ok, "测试"),
                                  (shots, shots_ok, "截图"), (videos, videos_ok, "录像"),
                                  (logs, logs_ok, "日志"), (raw, raw_ok, "原始抓取")):
        warnings.extend(f"[{feat['id']}] {label}路径不存在: {p}" for p in paths if p not in present)

    runs = reviewed_runs(feat)
    verdicts = platform_verdicts(feat, runs, warnings)
    final = aggregate_status(feat, verdicts, impl_ok)
    if not feat.get("platforms"):
        warnings.append(f"[{feat['id']}] 未声明适用平台，平台状态无法汇总")

    attributed = {m["path"] for v in verdicts for m in v["media"]}
    attributed |= {x for v in verdicts for x in (v["logs"] + v["raw"])}
    attributed |= {a["path"] for v in verdicts for o in v.get("observations", []) for a in o.get("assets", []) if a.get("exists")}
    unattributed = {
        "screenshots": [p for p in shots_ok if p not in attributed],
        "videos": [p for p in videos_ok if p not in attributed],
        "logs": [p for p in logs_ok if p not in attributed],
        "raw": [p for p in raw_ok if p not in attributed],
    }

    paths = impl_ok + tests_ok
    verified_at = git("log", "-1", "--format=%cI", "--", *paths) if paths else None
    accepted_at = max((v["verified_at"] for v in verdicts if v["verified_at"]), default=None)

    return {
        **feat,
        "status": final,
        "platform_status": [{"id": v["id"], "name": v["name"], "status": v["status"],
                             "verified_at": v["verified_at"], "run_count": len(v["runs"]),
                             "accepted_count": len(v["accepted"])} for v in verdicts],
        "verdicts": verdicts,
        "acceptance": [r for v in verdicts for r in v["accepted"]],
        "accepted_at": accepted_at,
        "unattributed": unattributed,
        "evidence": {
            "runs": [p for p in ev.get("runs", []) if path_exists(p)],
            "review": ev.get("review"),
            "impl": impl_ok,
            "api": ev.get("api", []) or [],
            "tests": tests_ok,
            "ci": ci_ok,
            "docs": docs_ok,
            "screenshots": shots_ok,
            "videos": videos_ok,
            "logs": logs_ok,
            "raw": raw_ok,
        },
        "verified_at": verified_at[:10] if verified_at else None,
    }


def load_platform_levels() -> dict[str, str]:
    """从 FHD/VERSION.md「各端交付等级」表自动读取对外口径。"""
    levels: dict[str, str] = {}
    source = REPO_ROOT / "FHD" / "VERSION.md"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return levels
    in_section = False
    for line in text.splitlines():
        if "各端交付等级" in line:
            in_section = True
            continue
        if in_section and line.strip().startswith("|"):
            cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
            # cells[0].strip("-: ") 为空即分隔行（`----` / `:---:` 等），不按固定字符串枚举。
            if len(cells) >= 3 and cells[0] not in ("端",) and cells[0].strip("-: ") and "：" not in cells[0]:
                levels[cells[0]] = cells[1]
        elif in_section and line.strip() and not line.strip().startswith("|"):
            break
    return levels


def load_product_version() -> str:
    """从 FHD/VERSION.md 读取稳定产品版本，官网不写死版本号。"""
    try:
        text = (REPO_ROOT / "FHD" / "VERSION.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"XCAGI 稳定产品版本\*\*\s*\|\s*`([^`]+)`", text)
    return m.group(1) if m else ""


def completion(features: list[dict]) -> int:
    """按 COMPLETION_WEIGHT 加权计算一组能力的完成度百分比（四舍五入）。"""
    if not features:
        return 0
    weighted = sum(COMPLETION_WEIGHT.get(f["status"], 0.0) for f in features)
    return int(round(weighted / len(features) * 100))


def build(repo_root_note: bool = True) -> tuple[dict, list[str], list[dict]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    warnings: list[str] = []
    domains_out: list[dict] = []
    feature_index: list[dict] = []

    id_to_name = {
        feat["id"]: feat["name"]
        for dom in catalog["domains"]
        for mod in dom["modules"]
        for feat in mod["features"]
    }

    for dom in catalog["domains"]:
        modules_out = []
        for mod in dom["modules"]:
            feats_out = []
            for feat in mod["features"]:
                if "status" in feat:
                    # 硬守卫：总体状态只能由平台状态自动汇总，不接受目录里手写。
                    raise SystemExit(
                        f"目录 {feat['id']} 仍声明 status={feat['status']!r}；"
                        "能力状态必须由平台实机验收记录自动汇总，禁止手写。")
                enriched = validate_feature(feat, warnings)
                featured = feat.get("featured", True) is not False
                evidence_ref = feat.get("evidence_ref") or None
                enriched = {
                    **enriched,
                    "featured": featured,
                    "evidence_ref": evidence_ref,
                    "evidence_ref_name": id_to_name.get(evidence_ref) if evidence_ref else None,
                    "excluded": bool(feat.get("cancelled")),
                }
                feats_out.append(enriched)
                feature_index.append(
                    {
                        "id": enriched["id"],
                        "name": enriched["name"],
                        "status": enriched["status"],
                        "domain_id": dom["id"],
                        "domain_name": dom["name"],
                        "module_id": mod["id"],
                        "module_name": mod["name"],
                        "platforms": enriched.get("platforms", []),
                        "platform_status": enriched["platform_status"],
                        "summary": enriched.get("summary", ""),
                        "featured": featured,
                        "evidence_ref": evidence_ref,
                        "evidence_ref_name": enriched["evidence_ref_name"],
                        "excluded": enriched["excluded"],
                    }
                )
            modules_out.append({**mod, "features": feats_out})
        domains_out.append({**dom, "modules": modules_out})

    stats = compute_stats(domains_out, feature_index)
    data = {
        "_comment": "此文件由 成都修茈科技有限公司/scripts/build_capability_center.py 自动生成，请勿手改（DO NOT EDIT）。",
        "schema_version": 1,
        "catalog_version": catalog.get("catalog_version", ""),
        "principle": "No Evidence, No Claim：总体状态由各平台实机验收记录自动汇总，目录不存放可手写的状态；缺证据的平台固定显示「待验证」。",
        "stats": stats,
        "product_version": load_product_version(),
        "platform_levels": load_platform_levels(),
        "deployment_modes": catalog.get("deployment_modes", []) or [],
        "next_plan": catalog.get("next_plan", []) or [],
        "domains": [
            {
                "id": d["id"],
                "name": d["name"],
                "description": d.get("description", ""),
                "modules": [
                    {
                        "id": m["id"],
                        "name": m["name"],
                        "features": [
                            {
                                "id": f["id"],
                                "name": f["name"],
                                "status": f["status"],
                                "platforms": f.get("platforms", []),
                                "platform_status": f["platform_status"],
                                "summary": f.get("summary", ""),
                                "featured": f["featured"],
                                "evidence_ref": f["evidence_ref"],
                                "evidence_ref_name": f["evidence_ref_name"],
                            }
                            for f in m["features"]
                            if not f["excluded"]
                        ],
                    }
                    for m in d["modules"]
                    if any(not f["excluded"] for f in m["features"])
                ],
            }
            for d in domains_out
            if any(not f["excluded"] for m in d["modules"] for f in m["features"])
        ],
    }
    return data, warnings, domains_out


def compute_stats(domains_out: list[dict], feature_index: list[dict]) -> dict:
    active = [f for f in feature_index if not f.get("excluded")]
    by_status = {s: 0 for s in STATUS_ORDER}
    for f in active:
        by_status[f["status"]] += 1
    verified_times = []
    for d in domains_out:
        for m in d["modules"]:
            for f in m["features"]:
                # 记录最近一次「任一平台实机验收通过」的时间，而不是只有全平台通过才记。
                for ps in f.get("platform_status", []):
                    if ps.get("verified_at"):
                        verified_times.append(ps["verified_at"])
    platform_counts: dict[str, int] = {}
    for f in active:
        for p in f["platforms"]:
            platform_counts[p] = platform_counts.get(p, 0) + 1
    # 逐平台验证覆盖：每个平台有多少项适用能力、其中多少项已通过该平台实机验收。
    platform_coverage: dict[str, dict] = {}
    for f in active:
        for ps in f.get("platform_status", []):
            row = platform_coverage.setdefault(
                ps["id"], {"applicable": 0, "verified": 0, "partial": 0, "pending": 0,
                           "last_verified_at": None})
            row["applicable"] += 1
            row[ps["status"]] = row.get(ps["status"], 0) + 1
            if ps.get("verified_at"):
                row["last_verified_at"] = max(row["last_verified_at"] or "", ps["verified_at"])
    return {
        "total": len(active),
        "by_status": by_status,
        "cancelled_count": len(feature_index) - len(active),
        "domains": len({f["domain_id"] for f in active}),
        "modules": len({(f["domain_id"], f["module_id"]) for f in active}),
        "verified_total": by_status["verified"],
        "last_verified_at": max(verified_times) if verified_times else None,
        "platform_counts": platform_counts,
        "platform_coverage": platform_coverage,
        "completion": completion(active),
    }



def css(href: str) -> str:
    return f'<link rel="stylesheet" href="{href}?v=20260922b" />'


def header_html(page_key: str, title_suffix: str, description: str, canonical: str) -> str:
    return f"""<!doctype html>
<!-- 此文件由 scripts/build_capability_center.py 自动生成，请勿手改（DO NOT EDIT）。 -->
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{esc(title_suffix)} | XCAGI</title>
    <meta name="description" content="{esc(description)}" />
    <meta property="og:site_name" content="XCAGI" />
    <meta property="og:title" content="{esc(title_suffix)} | XCAGI" />
    <meta property="og:description" content="{esc(description)}" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="https://xiu-ci.com{esc(canonical)}" />
    <meta property="og:image" content="https://xiu-ci.com/assets/brand-logo.jpg" />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="canonical" href="https://xiu-ci.com{esc(canonical)}" />
    <link rel="icon" href="/assets/xiu-ci-logo.png" type="image/png" />
    <link rel="stylesheet" href="/styles.css?v=20260925a" />
    {css("/capabilities/assets/capabilities.css")}
  </head>
<body data-page="{esc(page_key)}">
<header class="site-header"><div class="container header-inner">
<a class="brand-mark" href="/index.html"><span class="brand-seal"><img src="/assets/xiu-ci-logo.png" alt="修茈科技 Logo" /></span><span class="brand-name"><strong>XCAGI</strong><span>企业业务自动化平台</span></span></a>
<nav class="nav" aria-label="站点导航"><div class="nav-menu">
<a href="/index.html#product">产品</a><a href="/solutions.html">解决方案</a><a href="/cases.html">客户案例</a><a href="/index.html#pricing">价格</a><a href="/download">下载</a><a class="active" href="/capabilities/">验证中心</a><a href="/contact.html">联系我们</a>
<details class="nav-secondary"><summary>技术与透明度</summary><div class="nav-secondary-panel"><a href="/developer.html">开发者中心</a><a href="/world-will">世界意志</a><a href="/download/breakpoints">断点清单</a><a href="/download/goals">工作目标</a></div></details></div></nav>
<button class="mobile-menu-toggle" id="mobile-menu-toggle" type="button" aria-controls="mobile-menu" aria-label="打开菜单" aria-expanded="false"><span></span><span></span><span></span></button></div></header>
<div class="mobile-menu-overlay" id="mobile-menu-overlay"></div><nav class="mobile-menu" id="mobile-menu" aria-hidden="true" inert>
<a href="/index.html#product" class="mobile-menu-link">产品</a><a href="/solutions.html" class="mobile-menu-link">解决方案</a><a href="/cases.html" class="mobile-menu-link">客户案例</a><a href="/index.html#pricing" class="mobile-menu-link">价格</a><a href="/download" class="mobile-menu-link">下载</a><a href="/capabilities/" class="mobile-menu-link active">验证中心</a><a href="/contact.html" class="mobile-menu-link">联系我们</a>
<details class="mobile-secondary"><summary>技术与透明度</summary><a href="/developer.html" class="mobile-menu-link">开发者中心</a><a href="/world-will" class="mobile-menu-link">世界意志</a><a href="/download/breakpoints" class="mobile-menu-link">断点清单</a><a href="/download/goals" class="mobile-menu-link">工作目标</a></details></nav>
"""


def footer_html() -> str:
    return """<footer class="site-footer"><div class="container footer-inner"><div><a class="brand-mark" href="/index.html"><span class="brand-name"><strong>XCAGI</strong><span>企业业务自动化平台</span></span></a><p class="footer-copy">© <span id="year"></span> 成都修茈科技有限公司</p><p class="footer-meta">产品咨询：<a href="mailto:970882904@qq.com">970882904@qq.com</a></p><p class="footer-meta"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">蜀ICP备2026014056号-3A</a></p></div><nav class="footer-links" aria-label="页脚导航"><a href="/index.html#product">产品</a><a href="/solutions.html">解决方案</a><a href="/cases.html">客户案例</a><a href="/index.html#pricing">价格</a><a href="/download">下载</a><a href="/capabilities/">验证中心</a><a href="/contact.html">联系我们</a><details class="footer-secondary"><summary>技术与透明度</summary><a href="/developer.html">开发者中心</a><a href="/world-will">世界意志</a><a href="/download/breakpoints">断点清单</a><a href="/download/goals">工作目标</a></details></nav></div></footer><button id="back-to-top" class="back-to-top" aria-label="回到顶部"></button><script src="/main.js?v=20260925a"></script></body></html>"""


def render_index(data: dict, domains_full: list[dict]) -> str:
    s = data["stats"]
    version = data.get("product_version") or ""
    ver_html = f' <span class="capm-ver">v{esc(version)}</span>' if version else ""
    last_verified = s["last_verified_at"] or "—"

    cards = []
    for i, d in enumerate(domains_full):
        feats = [f for m in d["modules"] for f in m["features"] if f["featured"] and not f["excluded"]]
        all_feats = [f for m in d["modules"] for f in m["features"] if not f["excluded"]]
        pct = completion(all_feats)
        items = "".join(
            f'<li><a class="capm-feat" href="/capabilities/feature/{esc(f["id"])}.html">'
            f'<i class="capm-tick {TICK_CLASS[f["status"]]}" aria-hidden="true"></i>'
            f"<span>{esc(f['name'])}</span></a></li>"
            for f in feats
        )
        cards.append(
            f"""<article class="capm-card" style="--accent:{DOMAIN_ACCENTS[i % len(DOMAIN_ACCENTS)]}">
          <header class="capm-card-head"><h3>{esc(d['name'])}</h3><span class="capm-card-count">核心 {len(feats)} / 共 {len(all_feats)} 项</span></header>
          <ul class="capm-feats">{items}</ul>
          <footer class="capm-card-foot"><div class="capm-bar" role="img" aria-label="完成度 {pct}%"><span style="width:{pct}%"></span></div><span class="capm-pct">完成度 {pct}%</span></footer>
        </article>"""
        )

    # 右侧栏：三端产品形态，等级文案取自 FHD/VERSION.md，不另写口径。
    forms = []
    for form in PRODUCT_FORMS:
        levels = [v for v in (data.get("platform_levels", {}).get(k, "") for k in form["keys"]) if v]
        level = " / ".join(levels) or "见版本说明"
        warn = any("实验" in v or "非签约" in v for v in levels)
        forms.append(
            f"""<li class="capm-form"><div><strong>{esc(form['name'])}</strong><span>{esc(form['sub'])}</span></div>
          <em class="capm-badge {'capm-badge--warn' if warn else 'capm-badge--ok'}">{esc(level)}</em></li>"""
        )

    all_features = [f for d in domains_full for m in d["modules"] for f in m["features"] if not f["excluded"]]
    verified_features = [f for f in all_features if f["status"] == "verified"]
    verified_industry = [f for f in verified_features if f["id"].startswith("ind-")]
    verified_links = "".join(f'<li><a href="/capabilities/feature/{esc(f["id"])}.html">{esc(f["name"])} →</a></li>' for f in verified_features[:5]) or '<li>当前没有达到完整证据验收标准的能力项；可查看完整矩阵了解各项状态。</li>'
    industry_links = "".join(f'<li><a href="/capabilities/feature/{esc(f["id"])}.html">{esc(f["name"])} →</a></li>' for f in verified_industry) or '<li>当前没有行业 Mod 达到本矩阵的完整实机验收标准；目录条目不代表已交付。</li>'
    platform_cards = "".join(f'<li><strong>{esc(form["name"])}</strong><span>{esc(" / ".join(v for v in (data.get("platform_levels", {}).get(k, "") for k in form["keys"]) if v) or "见版本说明")}</span></li>' for form in CUSTOMER_PLATFORMS)
    customer_view = f'''<section class="cap-customer-view"><div class="container"><p class="home-kicker">XCAGI 客户能力视图</p><h1>从企业业务场景了解 XCAGI</h1><p>XCAGI 是对外产品名；XCMAX 是产品平台与工程体系的内部标识。客户购买、安装和使用的产品统一称为 XCAGI。</p><div class="cap-customer-grid"><article><h2>已验证能力</h2><p>当前共有 <strong>{len(verified_features)}</strong> 项能力达到本矩阵要求的全部适用平台实机验收标准。</p><ul>{verified_links}</ul></article><article><h2>行业 Mod</h2><p>以下只列出达到完整验收标准的行业能力。</p><ul>{industry_links}</ul><a href="/cases.html">查看客户案例与证据边界 →</a></article><article><h2>正式支持平台</h2><ul class="cap-customer-platforms">{platform_cards}</ul><p>平台等级来自 FHD/VERSION.md；下载开放状态以产品下载清单为准。</p></article></div><p class="cap-customer-cta"><a class="btn btn-primary" href="/download">查看产品下载</a><a class="btn btn-secondary" href="/contact.html#quick-inquiry">快速咨询</a><a class="cap-matrix-link" href="#technical-matrix">查看完整技术验证矩阵</a></p></div></section>'''

    modes = "".join(
        f'<li class="capm-mode"><strong>{esc(m["name"])}</strong>'
        f"<span>{esc(m.get('network', ''))} + {esc(m.get('storage', ''))}</span>"
        f"<em>{esc(m.get('desc', ''))}</em></li>"
        for m in data.get("deployment_modes", [])
    )

    pending = sorted(
        (
            f
            for d in domains_full
            for m in d["modules"]
            for f in m["features"]
            if not f["excluded"] and f["status"] != "verified"
        ),
        key=lambda f: STATUS_META[f["status"]]["rank"],
    )[:5]
    pending_items = "".join(
        f'<li><span class="capm-rank">{i + 1}</span>'
        f'<a href="/capabilities/feature/{esc(f["id"])}.html">{esc(f["name"])}</a>'
        f"{status_badge(f['status'])}</li>"
        for i, f in enumerate(pending)
    )

    plan_items = "".join(
        f'<li><span class="capm-rank">{i + 1}</span>'
        + (
            f'<a href="/capabilities/feature/{esc(x["feature"])}.html">{esc(x["text"])}</a>'
            if isinstance(x, dict) and x.get("feature")
            else f'<span>{esc(x["text"] if isinstance(x, dict) else x)}</span>'
        )
        + "</li>"
        for i, x in enumerate(data.get("next_plan", []))
    )

    legend = "".join(
        f'<li><i class="capm-tick {TICK_CLASS[k]}" aria-hidden="true"></i>'
        f'<strong>{STATUS_META[k]["label"]}</strong><span>{esc(desc)}</span></li>'
        for k, desc in STATUS_LEGEND
    )

    # 逐平台验证覆盖：平台无证据时也必须出现在页面上，显示为「待验证」，不隐藏。
    cov = data["stats"].get("platform_coverage", {})
    plat_rows = []
    for pid, m in PLATFORM_META.items():
        row = cov.get(pid)
        if not row:
            continue
        plat_rows.append(
            f'<tr><th scope="row">{esc(m)}</th>'
            f'<td>{row["applicable"]}</td>'
            f'<td><span class="cap-ps ps-verified">{row["verified"]}</span></td>'
            f'<td><span class="cap-ps ps-partial">{row["partial"]}</span></td>'
            f'<td><span class="cap-ps ps-pending">{row["pending"]}</span></td>'
            f'<td>{esc(row.get("last_verified_at") or "—")}</td></tr>'
        )
    plat_table = (
        '<section class="capm-panel capm-panel--platforms"><h2>各平台实机验收覆盖</h2>'
        '<p class="capm-panel-note">平台状态只由该平台的实机验收记录产生；'
        '没有任何实机验收记录的平台固定显示为「待验证」，不会因为其他平台通过而变绿。'
        '代码与自动化测试不计入平台状态。</p>'
        '<div class="cap-plat-table-wrap"><table class="cap-plat-table">'
        '<thead><tr><th scope="col">平台</th><th scope="col">适用能力</th>'
        '<th scope="col">已验证</th><th scope="col">部分验证</th><th scope="col">待验证</th>'
        '<th scope="col">最近通过</th></tr></thead>'
        f'<tbody>{"".join(plat_rows)}</tbody></table></div></section>'
    )

    return f"""{header_html("capabilities", "XCAGI 产品验证中心", "查看 XCAGI 已验证能力、正式支持平台与由证据自动生成的完整技术验证矩阵。", "/capabilities/")}
<main>
  {customer_view}
  <details class="cap-engineering" id="technical-matrix">
    <summary>查看完整技术验证矩阵（{s['total']} 项 · {s['completion']}% 加权工程进度）</summary>
    <p class="cap-engineering-intro">{s['completion']}% 是目录中不同实现/验证状态的加权工程进度，不表示“产品只有 39% 已开发”。所有状态、覆盖率和证据都由能力 SSOT、平台验收记录及 CI 门禁生成。</p>
  <section class="capm-hero">
    <div class="container capm-hero-inner">
      <div class="capm-hero-main">
        <h2><span class="capm-logo">XCAGI</span> 企业业务自动化平台{ver_html}</h2>
        <p class="capm-sub">跨平台 · 三端协同 · 一站式 AI 员工工作台</p>
        <p class="capm-slogan">把 AI 员工装进每台企业电脑，让企业自己运转</p>
      </div>
      <div class="capm-hero-side">
        <p class="capm-hero-quote">让 AI 员工<br />创造真实的生产力</p>
        <ul class="capm-hero-tags"><li>更高效</li><li>更智能</li><li>更自由</li></ul>
      </div>
    </div>
  </section>

  <section class="section capm-map-section" aria-labelledby="cap-map-title">
    <div class="container">
      <div class="capm-map-head">
        <h2 id="cap-map-title">全景功能地图</h2>
        <p class="capm-map-note">按「产品域 → 模块 → 功能」逐级展开，共 <strong>{s['total']}</strong> 项正式功能、{s['modules']} 个模块、{s['domains']} 个产品域。点击任一功能节点直达证据详情；移动端自动纵向折叠。</p>
      </div>
      <div class="capm-map-toolbar">
        <input type="search" id="cap-map-q" class="cap-search" placeholder="搜索功能名称…" aria-label="搜索功能" />
        <select id="cap-map-domain" aria-label="按产品域筛选"><option value="">全部产品域</option></select>
        <select id="cap-map-module" aria-label="按模块筛选"><option value="">全部模块</option></select>
        <select id="cap-map-status" aria-label="按状态筛选">
          <option value="">全部状态</option>
          <option value="verified">已验证</option>
          <option value="partial">部分验证</option>
          <option value="implemented">已实现待验证</option>
          <option value="planned">规划中</option>
        </select>
        <select id="cap-map-platform" aria-label="按平台筛选"><option value="">全部平台</option></select>
      </div>
      <p class="cap-map-result" id="cap-map-result" aria-live="polite"></p>
      <div class="capm-map" id="cap-map"></div>
    </div>
  </section>

  <div class="container capm-layout">
    <div class="capm-main">
      <div class="capm-matrix">{''.join(cards)}</div>

      <div class="capm-bottom">
        <section class="capm-panel capm-panel--progress">
          <h2>当前版本进度</h2>
          <div class="capm-progress-top"><div class="capm-bar capm-bar--lg"><span style="width:{s['completion']}%"></span></div><strong>{s['completion']}%</strong></div>
          <p class="capm-panel-note">总体完成度按加权口径计算：已验证 100%、部分验证 70%、已实现待验证 40%、规划中 0%，按正式功能数加权（已取消功能已从总数与完成度中剔除）。截至 {esc(last_verified or '—')}，共 {s['total']} 项正式功能、{s['modules']} 个模块、{s['domains']} 个产品域。</p>
          <ul class="capm-legend">{legend}</ul>
        </section>
        {plat_table}
        <section class="capm-panel">
          <h2>主要问题与待验收项（Top 5）</h2>
          <ol class="capm-list">{pending_items}</ol>
        </section>
        <section class="capm-panel">
          <h2>下一步重点计划（仅列未完成项）</h2>
          <ol class="capm-list">{plan_items}</ol>
        </section>
      </div>
    </div>

    <aside class="capm-side">
      <section class="capm-side-block">
        <h2>三端产品形态</h2>
        <ul class="capm-forms">{''.join(forms)}</ul>
        <p class="capm-panel-note">等级自动读取自产品版本说明 FHD/VERSION.md，非人工宣传口径。</p>
      </section>
      <section class="capm-side-block">
        <h2>安全与网络三模式</h2>
        <ul class="capm-modes">{modes}</ul>
      </section>
      <section class="capm-side-block capm-side-brand">
        <strong>XCAGI</strong>
        <span>AI EMPLOYEES FOR A BETTER BUSINESS</span>
        <em>成都修茈科技有限公司 · xiu-ci.com</em>
        <a class="btn btn-primary btn-sm" href="/capabilities/catalog.html">浏览完整能力目录</a>
      </section>
    </aside>
  </div>

  <section class="section">
    <div class="container">
      <h2>本页数字是怎么来的</h2>
      <p>能力目录 <code>data/capabilities/catalog.json</code> 由仓库审计维护；构建脚本 <code>scripts/build_capability_center.py</code> 在生成页面前逐项校验证据：实现路径、自动化测试、CI 工作流、文件存在只说明资料已收录；已验证还要求本项操作、预期与实际结果、构建身份及绑定原图哈希的内容复核记录。缺少验收记录会自动降级。矩阵中每个功能都可点进详情页查看对应证据。目录与页面由 CI 漂移门禁校验一致性，此检查不替代人工核验，也不代表全部功能已完成。</p>
    </div>
  </section>
  </details>
</main>
<script id="cap-catalog-data" type="application/json">{catalog_payload(data)}</script>
<script src="/capabilities/assets/panorama.js?v=20260919b"></script>
{footer_html()}"""


def render_catalog(data: dict) -> str:
    payload = catalog_payload(data)
    return f"""{header_html("capabilities", "能力目录", "XCAGI 完整能力目录：产品域→模块→功能三级结构，支持搜索与按平台、状态筛选。", "/capabilities/catalog.html")}
<main>
  <section class="page-hero page-hero--slim">
    <div class="container page-hero-inner">
      <div>
        <span class="eyebrow">Capability Catalog</span>
        <h1>能力目录</h1>
        <p>共 <strong>{data['stats']['total']}</strong> 项能力、{data['stats']['modules']} 个模块、{data['stats']['domains']} 个产品域。数字由目录自动统计。</p>
      </div>
      <div class="page-hero-side"><p><a class="btn btn-secondary btn-sm" href="/capabilities/">返回能力中心首页</a></p></div>
    </div>
  </section>
  <section class="section">
    <div class="container">
      <div class="cap-toolbar">
        <input type="search" id="cap-q" class="cap-search" placeholder="搜索功能名称或说明…" aria-label="搜索能力" />
        <select id="cap-domain" aria-label="按产品域筛选"><option value="">全部产品域</option></select>
        <select id="cap-status" aria-label="按状态筛选">
          <option value="">全部状态</option>
          <option value="verified">已验证</option>
          <option value="partial">部分验证</option>
          <option value="implemented">已实现待验证</option>
          <option value="planned">规划中</option>
        </select>
        <select id="cap-platform" aria-label="按平台筛选"><option value="">全部平台</option></select>
      </div>
      <p class="cap-result-note" id="cap-result-note" aria-live="polite"></p>
      <div id="cap-tree"></div>
    </div>
  </section>
</main>
<script id="cap-catalog-data" type="application/json">{payload}</script>
<script src="/capabilities/assets/catalog.js?v=20260919b"></script>
{footer_html()}"""


def evidence_list(items: list[str], cls: str = "") -> str:
    if not items:
        return '<p class="cap-evidence-empty">暂无</p>'
    lis = "".join(
        f'<li><code class="{cls}">{esc(i)}</code></li>' for i in items
    )
    return f'<ul class="cap-evidence-list">{lis}</ul>'


def platform_chips(verdicts: list[dict]) -> str:
    """适用平台固定全列，每个平台带自己的状态；缺证据的平台显示「待验证」，不隐藏。"""
    out = []
    for v in verdicts:
        meta = PLATFORM_STATUS_META[v["status"]]
        out.append(
            f'<span class="cap-platform cap-platform--{esc(v["status"])}">'
            f'{esc(v["name"])} · {meta["label"]}</span>'
        )
    return "".join(out)


def render_feature(f: dict, dom: dict, mod: dict, data: dict) -> str:
    ev = f["evidence"]
    review = json.loads(e(ev["review"]).read_text(encoding="utf-8")) if ev.get("review") else {}
    verdicts = f["verdicts"]
    collisions = platform_asset_collisions(f)
    ref = f.get("evidence_ref")
    panel = ""
    if ref:
        panel = (
            '<div class="cap-ref-note">'
            f'<p><strong>本项为功能地图中的明细能力</strong>，相关实现资料见核心能力「'
            f'{esc(f.get("evidence_ref_name") or ref)}」。上级能力的证据不能代替本项独立验收；本项已收录资料如下。</p>'
            f'<p><a class="btn btn-secondary btn-sm" '
            f'href="/capabilities/feature/{esc(ref)}.html">查看完整证据详情 →</a></p>'
            "</div>"
        )

    def asset(fid: str, path: str, platform: str | None = None) -> str:
        """证据资产在站点内的相对路径（构建时会把原始文件复制到 assets/evidence/）。"""
        return f"/capabilities/assets/evidence/{esc(evidence_asset_name(fid, path, platform, collisions))}"

    def run_lines(pairs: list[tuple[str, dict]], platform: str) -> str:
        if not pairs:
            return ""
        return "".join(
            f'<p class="cap-plat-run">验收结果：{esc(r.get("verdict") or r.get("status", "未知").upper())}；通过 {esc(r.get("passed", "见记录"))} / 失败 '
            f'{esc(r.get("failed", "见记录"))}；产品版本 {esc(r.get("app_version", "见记录"))}；'
            f'Git SHA <code>{esc(r.get("app_git_sha", ""))}</code>；'
            f'验证时间 {esc(r.get("verified_at", "见记录"))}。'
            f'<a href="{asset(f["id"], p, platform)}">Acceptance JSON</a> '
            f'SHA-256 <code>{esc(r.get("_acceptance_sha256", ""))}</code></p>'
            for p, r in pairs
        )

    def media_figs(media: list[dict], platform: str | None = None) -> str:
        """按运行记录绑定的媒体渲染；仅渲染已复核且哈希一致的条目。

        `outcome` 由调用方给出：只有绑定到平台验收记录的媒体才允许写「通过/失败」；
        未绑定平台的资料只写「资料收录」，不冒充验收结论。
        """
        videos, shots = [], []
        for m in media:
            p = m["path"]
            src = asset(f["id"], p, platform)
            outcome = esc(m.get("outcome") or "资料收录")
            digest = f"；SHA-256：{esc(m['sha256'])}" if m.get("sha256") else ""
            review = "原图内容已复核，" if m.get("visual_review") == "accepted" else ""
            cap = (f"{review}{outcome}{digest}"
                   f"（原始文件：{esc(p)}）")
            suffix = Path(p).suffix.lower()
            if suffix in (".mp4", ".webm", ".mov"):
                videos.append(
                    f'<figure class="cap-shot"><video controls preload="metadata" '
                    f'playsinline src="{src}"></video><figcaption>{cap}</figcaption></figure>')
            else:
                shots.append(
                    f'<figure class="cap-shot"><a class="cap-shot-link" href="{src}" '
                    f'target="_blank" rel="noopener"><img src="{src}" '
                    f'alt="{esc(f["name"])} 已复核截图" loading="lazy" /></a>'
                    f'<figcaption>{cap}</figcaption></figure>')
        out = ""
        if videos:
            out += ('<div class="cap-evidence-media"><h3>实机录像 / 操作流程</h3>'
                    f'<div class="cap-shots">{"".join(videos)}</div></div>')
        if shots:
            out += ('<div class="cap-evidence-media"><h3>实机截图</h3>'
                    f'<div class="cap-shots">{"".join(shots)}</div></div>')
        return out

    def log_blocks(paths: list[str], platform: str | None = None) -> str:
        """Expose raw logs as checksum-pinned downloads without duplicating them into every page."""
        out = []
        for p in paths:
            try:
                raw = e(p).read_bytes()
            except OSError:
                continue
            checksum = hashlib.sha256(raw).hexdigest()
            out.append(
                f'<div class="cap-evidence-block"><h3>运行日志</h3>'
                f'<p class="cap-evidence-note">'
                f'下载原件：<a href="{asset(f["id"], p, platform)}">{esc(Path(p).name)}</a>'
                    f'；SHA-256：<code>{checksum}</code>（仓库路径：{esc(p)}）</p></div>'
            )
        return "".join(out)

    def raw_block(paths: list[str], platform: str | None = None) -> str:
        """原始抓取：逐条原始产物的可核对副本（凭据值已脱敏，其余逐字保留）。"""
        out = []
        for p in paths:
            try:
                doc = json.loads(e(p).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            red = doc.get("_redaction", {}) or {}
            originals = red.get("originals", []) or []
            names = "、".join(esc(o.get("name", "")) for o in originals) or "见文件"
            out.append(
                '<div class="cap-evidence-block"><h3>原始抓取（脱敏）</h3>'
                f'<p>逐条原始产物汇编：{names}。'
                f'{esc(red.get("policy", "凭据值已脱敏，其余内容逐字保留。"))}'
                f'未经脱敏的原件留在操作机，逐件 sha256 记录在文件内。</p>'
                f'<p class="cap-evidence-note"><a href="{asset(f["id"], p, platform)}">'
                f'查看逐条原始抓取与原件 sha256 →</a>（仓库路径：{esc(p)}）</p></div>'
            )
        return "".join(out)

    def platform_run_blocks(v: dict) -> str:
        pairs = [(r["_acceptance_path"], r) for r in v["runs"]]
        media = [{**m, "outcome": "验收结果：" + {
            "passed": "通过", "failed": "失败", "blocked": "阻塞",
        }.get(r.get("status"), "未通过")} for _, r in pairs for m in r.get("media", [])]
        run_paths = {path for path, _ in pairs}
        return (run_lines(pairs, v["id"]) + media_figs(media, v["id"])
                + (log_blocks(v.get("logs", []), v["id"]) if pairs else "")
                + raw_block([p for p in v.get("raw", []) if pairs and p not in run_paths and p != v["identity_path"]], v["id"]))

    def artifact_block(v: dict) -> str:
        return (f'<p class="cap-plat-run">安装包 / 部署产物 SHA-256：<code>{esc(v["artifact_sha256"])}</code> · '
                f'<a href="{asset(f["id"], v["artifact_path"], v["id"])}">交付身份 JSON</a></p>'
                if v.get("artifact_sha256") else "")

    def observation_blocks(v: dict) -> str:
        blocks = []
        for item in v.get("observations", []):
            record_path, identity_path, assets = item["record_path"], item["identity_path"], item["assets"]
            media = [{"path": a["path"], "sha256": a.get("actual_sha256"), "outcome": "补充实机材料"}
                     for a in assets if a.get("exists") and a.get("kind") != "log"]
            logs = [a["path"] for a in assets if a.get("exists") and a.get("kind") == "log"]
            kinds = {a.get("kind"): a for a in assets}
            missing = [k for k in ("screenshot", "video", "log") if not kinds.get(k, {}).get("exists")]
            links = "来源 JSON 或身份 / 交付 JSON 缺失"
            if path_exists(record_path) and path_exists(identity_path):
                links = (f'<a href="{asset(f["id"], record_path, v["id"])}">来源 JSON</a> '
                         f'SHA-256 <code>{esc(item.get("record_sha256") or "缺失")}</code>')
                if identity_path != record_path:
                    links += f'；<a href="{asset(f["id"], identity_path, v["id"])}">身份 / 交付 JSON</a>'
            trace = "Git SHA 与交付 SHA 可追溯" if item["identity_traceable"] else "版本、Git SHA 或交付 SHA 无法完整追溯"
            details = (f'<p class="cap-plat-run">来源记录结果：{esc(item["record_result"])}（补充观察，不构成 PASS 验收）；'
                       f'产品版本：{esc(item.get("version") or "未记录")}；Git SHA：'
                       f'<code>{esc(item.get("git_sha") or "未记录")}</code>（{trace}）；'
                       f'安装包 / 交付 SHA-256：<code>{esc(item.get("artifact_sha256") or "未记录")}</code>；{links}</p>')
            notes = [esc(item["record_note"])] if item.get("record_note") else []
            notes.extend(("来源 JSON 与登记的 SHA-256 不匹配；本记录不用于平台转绿。",)
                         if not item.get("record_sha256_valid") else ())
            if item.get("identity_sha256") and identity_path != record_path:
                notes.append(f'身份 / 交付 JSON SHA-256：<code>{esc(item["identity_sha256"])}</code>')
            notes.extend(("身份 / 交付 JSON 未通过 SHA-256 校验；本记录不用于平台转绿。",)
                         if not item.get("identity_sha256_valid") else ())
            if missing:
                notes.append(f'证据缺项：{esc("、".join(missing))}。此记录不用于平台转绿。')
            notes.extend(f'文件存在但未通过 SHA-256 校验：{esc(a["path"])}'
                         for a in assets if a.get("exists") and not a.get("sha256_valid"))
            notes = "".join(f'<p class="cap-plat-note">{note}</p>' for note in notes)
            blocks.append(f'<div class="cap-evidence-block"><h3>实机补充记录</h3>{details}{notes}'
                          f'{media_figs(media, v["id"])}{log_blocks(logs, v["id"])}</div>')
        return "".join(blocks)

    # 逐平台区块：平台清单固定，状态与证据都挂在自己的平台上。
    plat_sections = []
    verified_plats = [v["name"] for v in verdicts if v["status"] == "verified"]
    pending_plats = [v["name"] for v in verdicts if v["status"] == "pending"]
    for v in verdicts:
        meta = PLATFORM_STATUS_META[v["status"]]
        if v["status"] == "pending":
            intro = ("该平台尚无完整且通过的实机验收记录。" if v["observations"] or v["runs"]
                     else "该平台尚无实机验收记录。")
            body = (
                f'<p class="cap-plat-note">{intro}平台状态只由该平台的实机验收产生，'
                '代码与自动化测试不计入；本项在此平台保持「待验证」，不会因其他平台通过而变绿。</p>'
                '<p class="cap-plat-note">变为已验证需要完整 PASS acceptance JSON、可追溯的产品版本和 Git SHA、交付身份 JSON 与安装包 / 部署产物 SHA-256，以及引用有效且哈希匹配的截图、录像和运行日志。</p>'
            ) + platform_run_blocks(v) + artifact_block(v) + observation_blocks(v)
        else:
            body = platform_run_blocks(v) + artifact_block(v) + observation_blocks(v)
        plat_sections.append(
            f'<section class="cap-plat cap-plat--{esc(v["status"])}">'
            f'<div class="cap-plat-head"><h3>{esc(v["name"])}</h3>'
            f'<span class="cap-ps {meta["cls"]}">{meta["label"]}</span></div>{body}</section>'
        )
    plat_section = (
        '<section class="section cap-plat-section"><div class="container">'
        '<h2>平台验证状态</h2>'
        '<p class="cap-section-note">本项适用于 ' 
        f'{len(verdicts)} 个平台，逐平台独立判定：平台状态只由该平台的实机验收记录产生，'
        '总体状态由平台状态自动汇总，目录与页面都不存放可手写的状态。</p>'
        + "".join(plat_sections) + "</div></section>"
    )

    remarks = []
    if verified_plats and pending_plats:
        remarks.append(
            f'当前仅在 {esc("、".join(verified_plats))} 通过实机验收；'
            f'{esc("、".join(pending_plats))} 仍为「待验证」，因此总体状态不构成「已验证」。')
    elif pending_plats and not verified_plats:
        has_attempts = any(v["runs"] or v["observations"] for v in verdicts)
        if has_attempts:
            remarks.append(
                f'本项在 {esc("、".join(pending_plats))} 上尚无完整 PASS 实机验收记录，'
                '不完整记录与补充观察均不计入已验证状态；当前状态仅表示代码已合入。')
        else:
            remarks.append(
                f'本项在 {esc("、".join(pending_plats))} 上均无实机验收记录，'
                '当前状态仅表示代码已合入，不代表任何平台验证通过。')
    plat_remark = f'<p class="cap-section-note">{"".join(remarks)}</p>' if remarks else ""

    # 未标注平台的历史资料：不参与任何平台状态。
    un = f["unattributed"]
    un_media = [{"path": p, "outcome": "资料收录（未绑定平台验收）"}
                for k in ("screenshots", "videos") for p in un.get(k, [])]
    un_html = ""
    if un_media or un.get("logs") or un.get("raw"):
        un_html = (
            '<div class="cap-evidence-media"><h3>未标注平台的补充资料</h3>'
            '<p class="cap-evidence-note">下列资料未绑定到具体平台，仅作实现与历史资料参考，'
            '不计入任何平台状态，也不构成实机验收。</p>'
            f'{media_figs(un_media)}{log_blocks(un.get("logs", []))}{raw_block(un.get("raw", []))}</div>'
        )


    verified_time = f.get("verified_at") or "—"
    limitations = (
        "".join(f"<li>{esc(x)}</li>" for x in f.get("limitations", [])) or "<li>暂未记录</li>"
    )
    usage = f.get("usage", "") or "请联系我们获取演示或参阅关联文档。"
    review_note = (
        f'<p class="cap-section-note">图片内容复核（{esc(review.get("reviewed_at", "待补"))}，'
        f'Mac {esc(review.get("app_version", "待补"))}）：{esc(review.get("visible_content", "尚无本项图片内容复核记录"))}</p>'
        if review else ""
    )
    docs_html = f'<div class="cap-evidence-block"><h3>关联文档</h3>{evidence_list(ev["docs"])}</div>' if ev["docs"] else ""
    api_html = f'<div class="cap-evidence-block"><h3>API 端点</h3>{evidence_list(ev["api"])}</div>' if ev["api"] else ""

    return f"""{header_html("capabilities", f["name"], f"{f['name']}：{f.get('summary', '')}", f"/capabilities/feature/{f['id']}.html")}
<main>
  <section class="page-hero page-hero--slim">
    <div class="container page-hero-inner">
      <div>
        <span class="eyebrow">{esc(dom['name'])} / {esc(mod['name'])}</span>
        <h1>{esc(f['name'])}</h1>
        <div class="cap-feature-meta">{status_badge(f['status'])}{platform_chips(verdicts)}</div>
        <p>{esc(f.get('summary', ''))}</p>
      </div>
      <div class="page-hero-side"><p><a class="btn btn-secondary btn-sm" href="/capabilities/catalog.html?domain={esc(dom['id'])}">返回 {esc(dom['name'])}</a></p></div>
    </div>
  </section>

  <section class="section">
    <div class="container cap-feature-top">
      <div class="cap-info-grid">
        <div class="cap-info-block"><h3>功能价值</h3><p>{esc(f.get('summary', ''))}</p></div>
        <div class="cap-info-block"><h3>使用方式</h3><p>{esc(usage)}</p></div>
        <div class="cap-info-block"><h3>所属模块</h3><p>{esc(dom['name'])} / {esc(mod['name'])}</p></div>
        <div class="cap-info-block"><h3>适用平台</h3><p>{platform_chips(verdicts) or '—'}</p></div>
        <div class="cap-info-block"><h3>当前状态</h3><p>{status_badge(f['status'])}（相关代码更新时间：{esc(verified_time)}）</p></div>
        <div class="cap-info-block"><h3>已知限制</h3><ul class="cap-limitations">{limitations}</ul></div>
      </div>
      {panel}
    </div>
  </section>

  {plat_section}

  <section class="section cap-evidence-section">
    <div class="container">
      <h2>实现与测试（平台无关）</h2>
      {plat_remark}
      {review_note}
      <div class="cap-evidence-grid">
        <div class="cap-evidence-block"><h3>源码实现</h3>{evidence_list(ev['impl'])}</div>
        {api_html}
        <div class="cap-evidence-block"><h3>自动化测试</h3>{evidence_list(ev['tests'])}<p class="cap-evidence-note">CI 门禁：{esc('、'.join(ev['ci']) if ev['ci'] else '待补本项 CI 证据')}</p></div>
        <div class="cap-evidence-block"><h3>CI 工作流定义</h3>{evidence_list(ev['ci'])}</div>
        {un_html}
        {docs_html}
      </div>
    </div>
  </section>
</main>
{footer_html()}"""


def write_outputs(data: dict, domains_full: list[dict]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    outputs["capabilities/index.html"] = render_index(data, domains_full)
    outputs["capabilities/catalog.html"] = render_catalog(data)
    for d in domains_full:
        for m in d["modules"]:
            for f in m["features"]:
                outputs[f"capabilities/feature/{f['id']}.html"] = render_feature(f, d, m, data)
    outputs["data/capabilities.json"] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return {p: "\n".join(line.rstrip() for line in body.splitlines()) + "\n"
            for p, body in outputs.items()}


def copy_evidence_assets(domains_full: list[dict]) -> list[str]:
    """Copy evidence assets; add platform suffixes only when basename collisions exist."""
    copied = []
    EVIDENCE_ASSET_DIR.mkdir(parents=True, exist_ok=True)

    def copy(feature: str, path: str, platform: str | None = None,
             collisions: set[str] | None = None) -> None:
        src = e(path)
        if src.is_file():
            dst = EVIDENCE_ASSET_DIR / evidence_asset_name(feature, path, platform, collisions)
            shutil.copy2(src, dst)
            copied.append(str(dst.relative_to(WEBSITE_DIR)))

    for d in domains_full:
        for m in d["modules"]:
            for f in m["features"]:
                collisions = platform_asset_collisions(f)
                # Unattributed catalog material keeps the legacy public name.
                for kind in ("screenshots", "videos", "runs", "review", "logs", "raw"):
                    paths = [f["evidence"][kind]] if kind == "review" and f["evidence"].get(kind) else f["evidence"].get(kind, []) or []
                    for p in paths:
                        if p:
                            copy(f["id"], p)
                for v in f.get("verdicts", []):
                    paths = [r["_acceptance_path"] for r in v["runs"]]
                    paths += [m["path"] for r in v["runs"] for m in r.get("media", [])]
                    paths += v["logs"] + v["raw"]
                    paths += [v.get("identity_path"), v.get("artifact_path")]
                    for observation in v["observations"]:
                        paths += [observation["record_path"], observation["identity_path"]]
                        paths += [a["path"] for a in observation["assets"]]
                    for p in dict.fromkeys(p for p in paths if p):
                        copy(f["id"], p, v["id"], collisions)
    return copied


def missing_public_evidence(domains: list[dict]) -> list[str]:
    missing = []
    for d in domains:
        for m in d["modules"]:
            for f in m["features"]:
                collisions = platform_asset_collisions(f)
                for v in f["verdicts"]:
                    paths = []
                    if v["status"] == "verified":
                        paths = [x["path"] for r in v["accepted"] for x in r["media"]]
                        paths += v["logs"] + v["raw"] + [r["_acceptance_path"] for r in v["accepted"]]
                        paths += [v["identity_path"], v["artifact_path"]]
                    paths += [o["record_path"] for o in v["observations"]]
                    paths += [o["identity_path"] for o in v["observations"]]
                    paths += [a["path"] for o in v["observations"] for a in o["assets"] if a["exists"]]
                    missing.extend(f"{f['id']}/{v['id']}: {p}" for p in paths
                                   if p and e(p).is_file()
                                   and not public_asset_matches(f["id"], p, v["id"], collisions))
    return missing


def prune_stale_generated(outputs: dict[str, str]) -> list[str]:
    """删除目录里已不在目录数据中的旧生成页。"""
    removed = []
    feat_dir = OUT_DIR / "feature"
    valid = {Path(k).name for k in outputs if k.startswith("capabilities/feature/")}
    if feat_dir.exists():
        for p in feat_dir.glob("*.html"):
            if p.name not in valid:
                removed.append(str(p.relative_to(WEBSITE_DIR)))
                p.unlink()
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="校验已提交文件与目录一致（CI 漂移门禁）")
    args = ap.parse_args()

    data, warnings, domains_full = build()
    evidence_errors = [w for w in warnings if w.startswith("ERROR ")]
    if evidence_errors and not args.check:
        for error in evidence_errors:
            print(error)
        return 1
    outputs = write_outputs(data, domains_full)

    if args.check:
        drift = []
        for rel, content in outputs.items():
            f = WEBSITE_DIR / rel
            if not f.exists():
                drift.append(f"缺失: {rel}")
                continue
            disk = f.read_text(encoding="utf-8")
            mem = content
            if disk == mem:
                continue
            drift.append(f"不一致: {rel}")
            dl, ml = disk.splitlines(), mem.splitlines()
            for i in range(max(len(dl), len(ml))):
                a = dl[i] if i < len(dl) else "<文件结束>"
                b = ml[i] if i < len(ml) else "<重生成结束>"
                if a != b:
                    drift.append(f"    已提交 L{i + 1}: {a.strip()[:160]}")
                    drift.append(f"    重生成 L{i + 1}: {b.strip()[:160]}")
                    break
        drift.extend(f"已验证平台公开证据缺失或哈希不匹配: {p}" for p in missing_public_evidence(domains_full))
        for w in warnings:
            print(w if w.startswith("ERROR ") else f"WARN {w}")
        drift.extend(f"证据来源或 SHA-256 校验失败: {w[6:]}" for w in evidence_errors)
        if drift:
            print("能力中心漂移门禁失败：目录与已提交页面不一致。请在仓库根目录运行：")
            print("  python3 '成都修茈科技有限公司/scripts/build_capability_center.py'")
            for d in drift:
                print(f"  - {d}")
            return 1
        print(f"能力中心校验通过：{data['stats']['total']} 项能力，证据状态与页面一致。")
        return 0

    for rel, content in outputs.items():
        target = WEBSITE_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    copied = copy_evidence_assets(domains_full)
    removed = prune_stale_generated(outputs)

    s = data["stats"]
    print(f"已生成能力中心：{s['total']} 项能力 / {s['modules']} 模块 / {s['domains']} 域")
    print(f"状态分布：{s['by_status']}")
    print(f"最近验证时间：{s['last_verified_at']}")
    print(f"证据资产复制（截图/录像）：{len(copied)} 个；清理过期页：{len(removed)} 个")
    if warnings:
        print(f"\n构建警告 {len(warnings)} 条：")
        for w in warnings:
            print(f"  {w}")
    else:
        print("构建警告：0 条；文件校验通过不代表功能验收通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
