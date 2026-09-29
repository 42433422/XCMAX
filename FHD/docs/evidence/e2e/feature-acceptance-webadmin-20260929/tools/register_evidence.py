#!/usr/bin/env python3
"""把本轮验收产物登记进能力目录 SSOT（catalog.json）。

只做「登记既有真实产物」这一件事：
  * 复核 run/identity 存在、录像存在、每个 media 文件的 sha256 现算；
  * 把人工复核结果写回 run 的 media（visual_review / visible_result / reviewed_at）；
  * 在 catalog.json 的该能力上写入 evidence.runs / screenshots / videos / logs / raw 与
    evidence.platform_assets.<platform>（acceptance / identity / artifact / logs / raw）。

复核口径：spec 必须为每个截图声明 VISIBLE_RESULTS 文案（人工实际看过才允许声明），
缺声明即报错退出，避免「未看先标 accepted」。

身份与交付物默认取本执行器写的 identity JSON；macOS 项可在 spec 里用 IDENTITY / ARTIFACT
显式指定（例如用 DMG 交付台账做 artifact）。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
CATALOG = REPO_ROOT / "成都修茈科技有限公司/data/capabilities/catalog.json"
EVID_ROOT = "FHD/docs/evidence/e2e/feature-acceptance-webadmin-20260929/tools/runs"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    return str(p.resolve().relative_to(REPO_ROOT))


def repo_rel(p) -> str:
    """把（可能是仓库相对的）路径规范成仓库相对路径，不依赖调用时的 CWD。"""
    pp = Path(p)
    if not pp.is_absolute():
        pp = REPO_ROOT / pp
    return str(pp.resolve().relative_to(REPO_ROOT))


def load_spec(path: Path):
    spec = importlib.util.spec_from_file_location("accept_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--reviewed-at", default=date.today().isoformat())
    args = ap.parse_args()

    spec_path = Path(args.spec).resolve()
    mod = load_spec(spec_path)
    feature = mod.FEATURE
    platform = getattr(mod, "PLATFORM", "web")
    visible = dict(getattr(mod, "VISIBLE_RESULTS", {}) or {})

    run_dir = REPO_ROOT / EVID_ROOT / feature
    run_path = next(run_dir.glob(f"*-{platform}-run.json"), None)
    id_path = next(run_dir.glob(f"*-{platform}-identity.json"), None)
    if not run_path or not id_path:
        print(f"FAIL: 缺少 run/identity 产物于 {run_dir}", file=sys.stderr)
        return 2
    run = json.loads(run_path.read_text(encoding="utf-8"))
    identity = json.loads(id_path.read_text(encoding="utf-8"))
    if run.get("status") != "passed" or run.get("verdict") != "PASS":
        print(f"FAIL: 本轮 verdict={run.get('verdict')} status={run.get('status')}，拒绝登记", file=sys.stderr)
        return 3

    videos = sorted((run_dir / "video").glob("*.webm"))
    if not videos:
        print("FAIL: 本轮没有录像，拒绝登记", file=sys.stderr)
        return 4
    log_files = sorted((run_dir / "log").glob("*.log"))
    if not log_files:
        print("FAIL: 本轮没有日志，拒绝登记", file=sys.stderr)
        return 5

    # ---- 人工复核写回 media（未声明复核文案的文件一律拒绝）
    for m in run["media"]:
        name = Path(m["path"]).name
        key = "__video__" if name.endswith(".webm") else name
        if key not in visible:
            print(f"FAIL: 产物 {name} 未在 spec.VISIBLE_RESULTS 中声明人工复核结论，拒绝标记 accepted", file=sys.stderr)
            return 6
        m["visual_review"] = "accepted"
        m["visible_result"] = visible[key]
        m["reviewed_at"] = args.reviewed_at
        m["sha256"] = sha256_file(REPO_ROOT / m["path"])
    run["reviewed_at"] = args.reviewed_at
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    shots = [m["path"] for m in run["media"] if m["path"].endswith(".png")]
    vids = [m["path"] for m in run["media"] if m["path"].endswith(".webm")]
    run_rel, id_rel = rel(run_path), rel(id_path)
    log_rel = rel(log_files[-1])

    # 身份/交付物的 JSON 可由 spec 显式指定（例如 macOS 项用 DMG 交付台账做 artifact）。
    # 未指定则默认用本执行器写的 identity JSON；路径一律按仓库根解析，避免受调用时的 CWD 影响。
    raw_ident = dict(getattr(mod, "IDENTITY", {}) or {})
    ident = ({"path": repo_rel(raw_ident["path"]), "git_sha": raw_ident["git_sha"],
              "version": raw_ident["version"]} if raw_ident
             else {"path": id_rel, "git_sha": "site_git_sha", "version": "site_version"})
    for extra in ("sha256",):
        if extra in raw_ident:
            ident[extra] = raw_ident[extra]
    raw_art = dict(getattr(mod, "ARTIFACT", {}) or {})
    art = ({"path": repo_rel(raw_art["path"]), "sha256": raw_art["sha256"],
            "git_sha": raw_art["git_sha"], "version": raw_art["version"]} if raw_art
           else {"path": id_rel, "sha256": "admin_console_dist_sha256",
                 "git_sha": "site_git_sha", "version": "site_version"})

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    target = None
    for dom in catalog["domains"]:
        for m in dom["modules"]:
            for f in m["features"]:
                if f["id"] == feature:
                    target = f
    if target is None:
        print(f"FAIL: catalog.json 中找不到能力 {feature}", file=sys.stderr)
        return 7

    ev = target.setdefault("evidence", {})
    # 只增不替换：同仓其它平台（如 macOS 轮次）的资产与媒体必须保留，否则会把别的平台证据抹掉。
    # 但同一能力的本轮目录（EVID_ROOT/<feature>/）里，若旧条目指向已被本轮重跑删除的产物
    # （重跑前会清掉上一轮录像/截图），必须同步剔除，否则目录会引用不存在的文件。
    prefix = f"{EVID_ROOT}/{feature}/"

    def merge_list(key: str, add: list) -> None:
        kept = [x for x in (ev.get(key) or []) if x not in add and not x.startswith(prefix)]
        ev[key] = kept + add

    merge_list("runs", [run_rel])
    merge_list("screenshots", shots)
    merge_list("videos", vids)
    merge_list("logs", [log_rel])
    merge_list("raw", sorted({id_rel, ident["path"], art["path"]}))

    assets = dict(ev.get("platform_assets") or {})
    assets[platform] = {
        "acceptance": {
            "path": run_rel,
            "sha256": sha256_file(run_path),
            "required_case_ids": [c["id"] for c in run["cases"]],
        },
        "identity": ident,
        "artifact": art,
        "logs": [{"path": log_rel, "sha256": sha256_file(REPO_ROOT / log_rel)}],
        "raw": sorted({id_rel, ident["path"], art["path"]}),
    }
    ev["platform_assets"] = assets
    rewrite_evidence_block(feature, ev)
    print(json.dumps({"feature": feature, "run": run_rel, "cases": len(run["cases"]),
                      "screenshots": len(shots), "videos": len(vids), "log": log_rel},
                     ensure_ascii=False))
    return 0


def rewrite_evidence_block(feature: str, evidence: dict) -> None:
    """只替换该能力的 evidence 文本块，保留目录其余部分的手工紧凑排版。

    整个文件重新 json.dumps 会把手工排版的 catalog 全面重排（数千行噪声），
    因此这里定位「能力 id 位置」后的 evidence 对象并按大括号配对替换。
    """
    import re

    text = CATALOG.read_text(encoding="utf-8")
    m = re.search(r'"id"\s*:\s*"' + re.escape(feature) + r'"', text)
    if not m:
        raise SystemExit(f"catalog 中未定位到能力 id: {feature}")
    key = '"evidence":'
    j = text.find(key, m.end())
    if j < 0:
        raise SystemExit(f"catalog 中未定位到 {feature} 的 evidence")
    k = j + len(key)
    while text[k] in " \t\r\n":
        k += 1
    if text[k] != "{":
        raise SystemExit(f"{feature} 的 evidence 不是对象")
    depth, n, in_str, esc = 0, k, False, False
    while n < len(text):
        ch = text[n]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
        n += 1
    else:
        raise SystemExit(f"{feature} 的 evidence 大括号不配平")
    new_json = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    CATALOG.write_text(text[:k] + new_json + text[n + 1:], encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())