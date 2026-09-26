#!/usr/bin/env python3
"""官网发布验收门禁（fail-closed）：产出 site/data/site-release-acceptance.json。

检查项（对应任务书二十二/二十三/二十四/十五）：
  1. ssot_drift_test          public-site.json 与 SSOT 重新生成结果逐字节一致
  2. hardcoded_fact_violations 公开页面禁止手写事实（版本/价格/Git SHA/SHA256/能力数）
  3. video_test               公开视频：时长 ≤60s、poster 存在、SHA256 与证据记录一致、原始录像可追溯
  4. broken_links             本地链接/资源不 404
  5. runtime tests            移动端/桌面端/视频播放/HTTP Range —— 由验收运行时（Playwright）回填

result 规则：
  PENDING  存在未回填的 runtime 结果
  BLOCKED  存在静态违规（硬编码事实 / 视频 / 断链 / SSOT 漂移）
  PASS     全部通过
只有 result=PASS 才允许发布。

用法：
  python3 scripts/site_acceptance.py                    # 静态检查并写出验收 JSON
  python3 scripts/site_acceptance.py --runtime f.json   # 合并 Playwright 运行时结果后重判
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SITE_ROOT.parent
DATA_DIR = SITE_ROOT / "site" / "data"
ACCEPTANCE_OUT = DATA_DIR / "site-release-acceptance.json"

# 允许的例外必须写明理由，禁止为过门禁而无理由豁免。
HARDCODED_EXEMPTS: dict[str, list[str]] = {
    # "file.html": ["规则说明（会被原文匹配展示在报告中）"],
}

VERSION_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")
PRICE_RE = re.compile(r"¥\s*\d[\d,]*(?:\.\d+)?")
PRICE_YUAN_RE = re.compile(r"\b\d[\d,]{2,}\s*元")
CAP_COUNT_RE = re.compile(r"\b\d{2,}\s*项(?:能力|功能)")
PCT_CLAIM_RE = re.compile(r"(?:工程|完成度|进度)[^<>{]{0,12}\d{1,3}\s*%")

# SSOT 槽位：带这些属性的元素内容是「占位文本」，由 JS 从 public-site.json 校验注入，
# 允许存在占位值（价格/额度/平台状态）。槽位本身即 fail-closed 机制的组成部分。
SSOT_SLOT_RE = re.compile(
    r"<[^>]*data-(?:ssot-price|ssot-quota|platform-status|ssot(?:=\"[^\"]*\")?)[^>]*>.*?</[^>]*>",
    re.DOTALL,
)

RULES = {
    "version": VERSION_RE,
    "git_sha": GIT_SHA_RE,
    "sha256": SHA256_RE,
    "price": PRICE_RE,
    "price_yuan": PRICE_YUAN_RE,
    "capability_count": CAP_COUNT_RE,
    "percent_claim": PCT_CLAIM_RE,
}


def public_pages() -> list[Path]:
    pages = sorted(SITE_ROOT.glob("*.html")) + sorted((SITE_ROOT / "partials").glob("*.html"))
    # capabilities/ 目录为生成产物（由 build_capability_center.py 注入版本），不在本扫描范围。
    return [p for p in pages if p.name != "site-release-acceptance.json"]


def scan_hardcoded_facts() -> list[dict]:
    violations: list[dict] = []
    for page in public_pages():
        rel = str(page.relative_to(SITE_ROOT))
        text = page.read_text(encoding="utf-8")
        text = SSOT_SLOT_RE.sub(lambda m: re.sub(r">.*?<", "><", m.group(0), flags=re.DOTALL), text)
        lines = text.splitlines()
        for rule_name, regex in RULES.items():
            for i, line in enumerate(lines, 1):
                m = regex.search(line)
                if not m:
                    continue
                if any(x in line for x in HARDCODED_EXEMPTS.get(rel, [])):
                    continue
                violations.append(
                    {"file": rel, "line": i, "rule": rule_name, "match": m.group(0), "context": line.strip()[:160]}
                )
    return violations


def check_videos(public_site: dict) -> tuple[list[dict], bool]:
    problems: list[dict] = []
    videos = list(public_site.get("evidence", {}).get("videos", []))
    for case in public_site.get("cases", []):
        videos.extend(case.get("videos", []))
    for v in videos:
        f = v.get("file")
        local = SITE_ROOT / "capabilities" / "assets" / "evidence" / f if not str(v.get("public_path", "")).startswith("/capabilities") else SITE_ROOT / v["public_path"].lstrip("/")
        if not local.exists():
            problems.append({"file": f, "issue": "视频文件不存在"})
            continue
        if not v.get("duration_ok") or (v.get("duration_seconds") or 0) > 60:
            problems.append({"file": f, "issue": f"时长超 60s 或不可解析: {v.get('duration_seconds')}"})
        codec = v.get("codec")
        if f and f.endswith(".mp4") and codec != "avc1":
            problems.append({"file": f, "issue": f"MP4 非 H.264 编码（官网展示须 H.264）: {codec}"})
        if f and f.endswith(".webm"):
            problems.append({"file": f, "issue": "官网展示视频须为 H.264 MP4（webm 仅作原始材料）"})
        if not v.get("sha256"):
            problems.append({"file": f, "issue": "缺少 SHA256"})
        if not v.get("poster"):
            problems.append({"file": f, "issue": "缺少 poster 首帧图"})
        orig = v.get("original_recording")
        if not orig or not orig.get("sha256"):
            problems.append({"file": f, "issue": "原始录像不可追溯（缺 original_recording.sha256）"})
        if not v.get("public_path"):
            problems.append({"file": f, "issue": "无公开路径"})
    return videos, problems


def check_links(public_site: dict) -> list[str]:
    broken: list[str] = []
    # 运行时由后端 / nginx 独立服务的路由，不在静态目录检查范围。
    runtime_prefixes = ("/market", "/api", "/openapi.json", "/redoc", "/app")
    attrs = re.compile(r"""(?:href|src|poster)=["']([^"']+)["']""")
    for page in public_pages():
        text = page.read_text(encoding="utf-8")
        for m in attrs.finditer(text):
            url = m.group(1).strip()
            if url.startswith(("http://", "https://", "mailto:", "tel:", "#", "data:")):
                continue
            path = url.split("#")[0].split("?")[0]
            if not path:
                continue
            if any(path.startswith(p) for p in runtime_prefixes):
                continue
            rel = path.lstrip("/")
            candidates = [SITE_ROOT / rel]
            # nginx clean URL：/download/releases → download-releases.html；/capabilities/ → index.html
            dl = re.match(r"^download/([\w-]+)$", rel)
            if dl:
                candidates.append(SITE_ROOT / f"download-{dl.group(1)}.html")
            if not rel.endswith(".html") and "." not in Path(rel).name:
                candidates += [SITE_ROOT / (rel + ".html"), SITE_ROOT / rel / "index.html"]
            if not any(c.exists() for c in candidates):
                broken.append(f"{page.name} → {url}")
    return sorted(set(broken))


def check_ssot_drift() -> tuple[bool, str]:
    r = subprocess.run([sys.executable, str(SITE_ROOT / "scripts" / "build_public_site.py"), "--check"], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-500:]


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError, subprocess.CalledProcessError):
        return "unknown"


def file_sha(path: Path) -> str | None:
    import hashlib

    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", help="Playwright 运行时结果 JSON（mobile_test/desktop_test/video_runtime_test/range_test）")
    args = ap.parse_args()

    public_site_path = DATA_DIR / "public-site.json"
    if not public_site_path.exists():
        print("[acceptance] FAIL: public-site.json 不存在，先运行 build_public_site.py", file=sys.stderr)
        raise SystemExit(1)
    public_site = json.loads(public_site_path.read_text(encoding="utf-8"))

    fact_violations = scan_hardcoded_facts()
    broken_links = check_links(public_site)
    videos, video_problems = check_videos(public_site)
    video_ok = not video_problems
    drift_ok, drift_msg = check_ssot_drift()

    runtime = {}
    if args.runtime:
        runtime = json.loads(Path(args.runtime).read_text(encoding="utf-8"))
    mobile_test = runtime.get("mobile_test", "pending")
    desktop_test = runtime.get("desktop_test", "pending")
    video_runtime_test = runtime.get("video_runtime_test", "pending")
    range_test = runtime.get("range_test", "pending")

    static_ok = not fact_violations and not broken_links and video_ok and drift_ok
    if not static_ok:
        result = "BLOCKED"
    elif "pending" in (mobile_test, desktop_test, video_runtime_test, range_test):
        result = "PENDING"
    elif all(x == "pass" for x in (mobile_test, desktop_test, video_runtime_test, range_test)):
        result = "PASS"
    else:
        result = "BLOCKED"

    report = {
        "schema": "xcagi.site_release_acceptance/v1",
        "release_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha(),
        "site_build_sha": file_sha(public_site_path),
        "version": public_site.get("product", {}).get("version"),
        "pricing_ssot_sha": file_sha(REPO_ROOT / "FHD" / "config" / "saas_plans.json"),
        "capability_ssot_sha": file_sha(SITE_ROOT / "data" / "capabilities.json"),
        "release_manifest_sha": file_sha(SITE_ROOT / "download-release.json"),
        "cases_ssot_sha": file_sha(REPO_ROOT / "FHD" / "config" / "public_cases.json"),
        "page_count": len(public_pages()),
        "broken_links": broken_links,
        "hardcoded_fact_violations": fact_violations,
        "video_test": "pass" if video_ok else "fail",
        "video_problems": video_problems,
        # 上游证据漂移（run.json 记录 vs 仓库实际文件）——独立登记，不并入 result：
        # 这些媒体已被拒绝发布（public_path=None），矛盾透明归档，由证据责任方修正。
        "upstream_evidence_drift": public_site.get("evidence", {}).get("integrity_problems", []),
        "video_inventory": [
            {"file": v.get("file"), "duration_seconds": v.get("duration_seconds"), "codec": v.get("codec"), "sha256": (v.get("sha256") or "")[:16], "poster": v.get("poster")}
            for v in videos
        ],
        "ssot_drift_test": "pass" if drift_ok else "fail",
        "ssot_drift_detail": drift_msg if not drift_ok else "",
        "mobile_test": mobile_test,
        "desktop_test": desktop_test,
        "video_runtime_test": video_runtime_test,
        "range_test": range_test,
        "result": result,
        "_gate": "result=PASS 才允许发布；BLOCKED 必须修复；PENDING 需回填运行时结果。禁止改断言、改结果字段或删测试来过门禁。",
    }
    ACCEPTANCE_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[acceptance] facts={len(fact_violations)} broken_links={len(broken_links)} videos={'ok' if video_ok else 'FAIL'} drift={'ok' if drift_ok else 'FAIL'} runtime=[{mobile_test},{desktop_test},{video_runtime_test},{range_test}]")
    print(f"[acceptance] result={result} → {ACCEPTANCE_OUT}")
    if fact_violations:
        for v in fact_violations[:20]:
            print(f"  [fact] {v['file']}:{v['line']} {v['rule']} = {v['match']}  | {v['context'][:100]}")
    if broken_links:
        for b in broken_links[:20]:
            print(f"  [link] {b}")
    if not video_ok:
        for p in video_problems:
            print(f"  [video] {p.get('file')} {p.get('issue')}")
    raise SystemExit(0 if static_ok else 1)


if __name__ == "__main__":
    main()
