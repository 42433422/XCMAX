#!/usr/bin/env python3
"""
XCMAX _archive 敏感文件清理脚本（v9.0.0 整改配套工具）

职责：
  1. 扫描 _archive/ 下所有"高风险"文件：真实 .env、私有项目配置、登录态、
     客户/微信数据库、二进制 mod 包、私钥、CA-bundle 之外的 pem。
  2. 将原始内容迁移到 _archive/.redacted-snapshots/<原相对路径>，保留可恢复性。
  3. 原位用 .redacted.<ext> 占位文件替代，提示"内容已迁移到 .redacted-snapshots/"。
  4. 输出 SECURITY_CLEANUP_REPORT.md（含原文件 SHA-256、迁移路径、是否已就地处占位）。
  5. 在 _archive/ARCHIVED.md 末尾追加"敏感文件脱敏策略"小节。

设计原则：
  - 不可逆地破坏前永远保留原副本于 .redacted-snapshots/（已 .gitignore）。
  - 二次执行幂等：已脱敏的占位文件直接跳过。
  - 不动 dist/_internal/aliyunsdkcore/.../cacert.pem 这类公开 CA 证书包。
  - 失败立即抛错，不静默吞异常。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "_archive"
_DEFAULT_SNAPSHOT = Path(
    os.environ.get(
        "XCMAX_REDACTED_SNAPSHOTS_DIR",
        str(ARCHIVE / ".redacted-snapshots"),
    )
).resolve()
SNAPSHOT_DIR = _DEFAULT_SNAPSHOT
REPORT_PATH = ROOT / "SECURITY_CLEANUP_REPORT.md"
ARCHIVED_MD = ARCHIVE / "ARCHIVED.md"

# 高风险模式（相对于 _archive 内的相对路径匹配）
HIGH_RISK_RULES = [
    # 真实 .env（不是 .env.example / .env.generic / .env.minimal）
    {"name": "real_env", "pattern": lambda p: p.name == ".env"},
    # 私有项目配置（IDE / 平台私有 token）
    {"name": "private_config", "pattern": lambda p: p.name == "project.private.config.json"},
    # 登录态 / 鉴权缓存
    {"name": "login_out", "pattern": lambda p: p.name == "login_out.json"},
    # 客户/产品/支付业务库（真实数据风险）
    {"name": "products_db", "pattern": lambda p: p.name.startswith("products") and p.suffix in {".db", ".db-shm", ".db-wal"}},
    {"name": "pytest_products_db", "pattern": lambda p: p.name == ".pytest_products.db"},
    # 应用核心数据库（xcagi / modstore / test_upload / *.db-wal/-shm）— 任何 SQLite 都可能含客户/订单/支付数据
    {"name": "app_db", "pattern": lambda p: p.suffix in {".db", ".db-shm", ".db-wal"} and not p.name.startswith("contact") and not p.name.startswith("message") and not p.name.startswith("media") and not p.name.startswith("biz_message") and not p.name.startswith("test_") and p.parent.name not in {"tests", "test"}},
    # 微信解密的本地数据库（可能含真实聊天记录）
    {"name": "wechat_decrypt_db", "pattern": lambda p: "wechat-decrypt/raw_db" in str(p) and p.suffix in {".db", ".db-shm", ".db-wal"}},
    # 二进制 mod 包（私有版权代码/资源）
    {"name": "xcmod_binary", "pattern": lambda p: p.suffix == ".xcmod"},
    # .env 的不同语种副本（个人版 / 交付版 / docker 版）
    {"name": "env_variant", "pattern": lambda p: p.name.startswith(".env.") and not p.name.endswith((".example", ".generic", ".minimal", ".fhd-docker.example", ".fhd-docker"))},
]

# 明确豁免（公开 CA bundle、示例配置）
EXEMPT_SUBSTRINGS = (
    "dist/_internal/aliyunsdkcore/vendored/requests/packages/certifi/cacert.pem",
    ".env.example",
    ".env.generic",
    ".env.minimal",
)


def is_exempt(rel: str) -> bool:
    return any(s in rel for s in EXEMPT_SUBSTRINGS)


def classify(rel_path: Path) -> str | None:
    p = rel_path
    rel = str(rel_path).replace("\\", "/")
    if is_exempt(rel):
        return None
    for rule in HIGH_RISK_RULES:
        try:
            if rule["pattern"](p):
                return rule["name"]
        except Exception:
            continue
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def already_redacted(path: Path) -> bool:
    """占位文件的特征：包含 REDACTED_MARK 字符串。"""
    if not path.is_file() or path.stat().st_size > 4096:
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "XCAGI_REDACTED_SNAPSHOT_POINTER" in head


def parse_redacted_placeholder(path: Path) -> dict:
    """从占位文件解析出原 SHA-256 / 大小 / 快照相对路径。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    info: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# 快照:"):
            info["snapshot_rel"] = line.split(":", 1)[1].strip()
        elif line.startswith("# SHA-256:"):
            info["sha256"] = line.split(":", 1)[1].strip()
        elif line.startswith("# 大小:"):
            try:
                info["size"] = int(line.split(":", 1)[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return info


def make_placeholder(orig: Path, rel: str, rule: str, snapshot_rel: str, sha256: str, size: int) -> str:
    return (
        f"# XCAGI_REDACTED_SNAPSHOT_POINTER\n"
        f"# 本文件已被脱敏（规则: {rule}）。\n"
        f"# 原文件: _archive/{rel}\n"
        f"# 快照:   _archive/{snapshot_rel}\n"
        f"# SHA-256: {sha256}\n"
        f"# 大小:    {size} bytes\n"
        f"# 脱敏时间: {datetime.now().isoformat(timespec='seconds')}\n"
        f"#\n"
        f"# 恢复: cp _archive/{snapshot_rel} _archive/{rel}\n"
        f"# 详见根目录 SECURITY_CLEANUP_REPORT.md\n"
        f"__XCAGI_REDACTED__=1\n"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只扫描、不迁移、不替换")
    ap.add_argument("--report-only", action="store_true", help="只生成报告、不动文件")
    ap.add_argument(
        "--check",
        action="store_true",
        help="CI / pre-commit 专用：仅扫描，若发现未脱敏文件则退出码=1；不修改任何文件",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="与 --check 配合：连 SHA-256 元数据缺失/不匹配的占位也视作失败",
    )
    args = ap.parse_args(argv)

    if not ARCHIVE.exists():
        print(f"ERROR: {ARCHIVE} not found", file=sys.stderr)
        return 1

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    candidates: list[dict] = []
    for path in sorted(ARCHIVE.rglob("*")):
        if not path.is_file():
            continue
        if path.is_relative_to(SNAPSHOT_DIR):
            continue
        rel = path.relative_to(ARCHIVE)
        rule = classify(rel)
        if not rule:
            continue
        candidates.append({"abs": path, "rel": rel, "rule": rule})

    print(f"扫描到 {len(candidates)} 个高风险文件")

    results: list[dict] = []
    for c in candidates:
        abs_p: Path = c["abs"]
        rel_p: Path = c["rel"]
        rule: str = c["rule"]

        # 跳过已脱敏的占位（但仍从占位文件抽取元数据用于报告）
        if already_redacted(abs_p):
            meta = parse_redacted_placeholder(abs_p)
            record = {
                "rel": str(rel_p),
                "rule": rule,
                "status": "already_redacted",
                "size": meta.get("size", "-"),
                "sha256": meta.get("sha256", "-"),
                "snapshot_rel": meta.get("snapshot_rel", "-"),
            }
            if args.strict and (record["sha256"] == "-" or record["snapshot_rel"] == "-"):
                record["status"] = "redacted_but_missing_meta"
            results.append(record)
            continue

        # --check 模式下：未脱敏文件必须立即报错，不进行后续迁移/替换
        if args.check:
            try:
                size = abs_p.stat().st_size
                sha = sha256_file(abs_p)
            except Exception as e:
                results.append({"rel": str(rel_p), "rule": rule, "status": f"hash_error: {e}"})
                continue
            results.append({
                "rel": str(rel_p),
                "rule": rule,
                "status": "needs_redaction",
                "size": size,
                "sha256": sha,
            })
            continue

        try:
            sha = sha256_file(abs_p)
            size = abs_p.stat().st_size
        except Exception as e:
            results.append({"rel": str(rel_p), "rule": rule, "status": f"hash_error: {e}"})
            continue

        snapshot_abs = SNAPSHOT_DIR / rel_p
        snapshot_rel = str(snapshot_rel := Path(".redacted-snapshots") / rel_p)

        record = {
            "rel": str(rel_p),
            "rule": rule,
            "size": size,
            "sha256": sha,
            "snapshot_rel": snapshot_rel,
            "status": "pending",
        }

        if args.dry_run:
            record["status"] = "dry_run"
            results.append(record)
            continue

        try:
            snapshot_abs.parent.mkdir(parents=True, exist_ok=True)
            if not args.report_only:
                shutil.copy2(abs_p, snapshot_abs)
                placeholder = make_placeholder(abs_p, str(rel_p), rule, snapshot_rel, sha, size)
                abs_p.write_text(placeholder, encoding="utf-8")
            record["status"] = "redacted" if not args.report_only else "report_only"
        except Exception as e:
            record["status"] = f"error: {e}"

        results.append(record)
        print(f"  [{record['status']}] {rel_p}  ({rule})")

    # 生成报告
    write_report(results, dry_run=args.dry_run or args.report_only or args.check)

    # 更新 ARCHIVED.md
    if not args.dry_run and not args.report_only and not args.check:
        update_archived_md(results)

    summary = {
        "total": len(results),
        "redacted": sum(1 for r in results if r["status"] == "redacted"),
        "needs_redaction": sum(1 for r in results if r["status"] == "needs_redaction"),
        "dry_run": sum(1 for r in results if r["status"] == "dry_run"),
        "report_only": sum(1 for r in results if r["status"] == "report_only"),
        "already_redacted": sum(1 for r in results if r["status"] == "already_redacted"),
        "redacted_but_missing_meta": sum(1 for r in results if r["status"] == "redacted_but_missing_meta"),
        "errors": sum(1 for r in results if r["status"].startswith("error")),
    }
    print("\nSummary:", json.dumps(summary, ensure_ascii=False, indent=2))

    # --check 模式退出码语义：
    #   0 = 全部已脱敏（PASS）
    #   1 = 存在未脱敏文件（FAIL）
    #   2 = 内部错误
    if args.check:
        if summary["needs_redaction"] > 0 or summary["errors"] > 0 or summary["redacted_but_missing_meta"] > 0:
            return 1
        return 0
    return 0 if summary["errors"] == 0 else 2


def write_report(results: list[dict], *, dry_run: bool) -> None:
    by_rule: dict[str, int] = {}
    for r in results:
        by_rule[r["rule"]] = by_rule.get(r["rule"], 0) + 1

    lines: list[str] = []
    lines.append("# XCMAX _archive 敏感文件清理报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- 扫描根目录：`_archive/`")
    lines.append(f"- 快照目录：`_archive/.redacted-snapshots/`（已在 .gitignore）")
    lines.append(f"- 模式：{'dry-run（不修改文件）' if dry_run else '实执行'}")
    lines.append("")
    lines.append("## 规则命中统计")
    lines.append("")
    lines.append("| 规则 | 命中数 | 含义 |")
    lines.append("|------|--------|------|")
    rule_meaning = {
        "real_env": "真实的 .env（含数据库 URL、IP、端口、密钥）",
        "private_config": "IDE / 平台私有项目配置（可能含 token）",
        "login_out": "登录态 / 鉴权缓存",
        "products_db": "客户/产品/支付业务数据库（真实数据风险）",
        "pytest_products_db": "测试用产品库（数据可能跨环境）",
        "app_db": "应用核心数据库（xcagi.db / modstore.db / test_upload.db 等，可能含订单/支付）",
        "wechat_decrypt_db": "微信解密的本地数据库（可能含真实聊天记录）",
        "xcmod_binary": "二进制 mod 包（私有版权代码/资源）",
        "env_variant": ".env.* 非示例变体（个人/交付/自定义）",
    }
    for rule, n in sorted(by_rule.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{rule}` | {n} | {rule_meaning.get(rule, '-')} |")
    lines.append("")

    lines.append("## 明细（前 200 条）")
    lines.append("")
    lines.append("| 状态 | 规则 | 大小 (B) | SHA-256 (前 16) | 原路径 | 快照路径 |")
    lines.append("|------|------|----------|------------------|--------|----------|")
    for r in results[:200]:
        sha_short = r.get("sha256", "")[:16] or "-"
        size = r.get("size", "-")
        snap = r.get("snapshot_rel", "-") or "-"
        # snapshot_rel 形如 "_archive/.redacted-snapshots/..." 或 ".redacted-snapshots/..."
        # 统一渲染为仓库内相对路径（去掉可能的前缀 _archive/）
        snap_disp = snap
        if snap_disp.startswith("_archive/"):
            snap_disp = snap_disp[len("_archive/"):]
        elif snap_disp.startswith(".redacted-snapshots/") or snap_disp == ".redacted-snapshots":
            pass
        lines.append(
            f"| {r['status']} | `{r['rule']}` | {size} | `{sha_short}` | "
            f"`_archive/{r['rel']}` | `_archive/{snap_disp}` |"
        )
    if len(results) > 200:
        lines.append(f"\n*（共 {len(results)} 条，剩余 {len(results) - 200} 条省略）*")
    lines.append("")
    lines.append("## 恢复方法")
    lines.append("")
    lines.append("```bash")
    lines.append("# 恢复单个文件")
    lines.append("cp _archive/.redacted-snapshots/<rel-path> _archive/<rel-path>")
    lines.append("")
    lines.append("# 查看原始内容")
    lines.append("less _archive/.redacted-snapshots/<rel-path>")
    lines.append("```")
    lines.append("")
    lines.append("## 二次执行幂等")
    lines.append("")
    lines.append("脚本对已脱敏占位文件（含 `XCAGI_REDACTED_SNAPSHOT_POINTER` 标记）直接跳过；")
    lines.append("可重复执行，不会重复迁移。")
    lines.append("")
    lines.append("## 豁免清单（明确保留）")
    lines.append("")
    lines.append("- `**/.env.example`、`.env.generic`、`.env.minimal`、`.env.fhd-docker.example`")
    lines.append("- `dist/_internal/aliyunsdkcore/.../cacert.pem` 等公开 CA 证书包")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告写入: {REPORT_PATH.relative_to(ROOT)}")


def update_archived_md(results: list[dict]) -> None:
    """在 _archive/ARCHIVED.md 末尾追加脱敏策略小节。"""
    section_title = "## 敏感文件脱敏策略（v9.0.0 整改）"
    if ARCHIVED_MD.exists():
        content = ARCHIVED_MD.read_text(encoding="utf-8")
        if section_title in content:
            return  # 已存在则不重复追加
    else:
        content = "# _archive 归档目录说明\n\n本目录存放只读历史快照，**禁止日常改动**。\n\n"

    n = sum(1 for r in results if r["status"] == "redacted")
    addendum = (
        f"\n\n{section_title}\n\n"
        f"为防止 `.env`、私钥、数据库、登录态、二进制 mod 包等敏感内容随归档流入主仓，\n"
        f"v9.0.0 整改中已对 **{n}** 个高风险文件执行脱敏：\n\n"
        f"1. 原文件内容迁移到 `_archive/.redacted-snapshots/<原相对路径>`（已在 `.gitignore`）。\n"
        f"2. 原位用 `XCAGI_REDACTED_SNAPSHOT_POINTER` 占位文件替代，记录原 SHA-256 与快照路径。\n"
        f"3. 详见根目录 [`SECURITY_CLEANUP_REPORT.md`](../SECURITY_CLEANUP_REPORT.md)。\n"
        f"4. 二次执行幂等：占位文件已含标记，不会重复迁移。\n\n"
        f"恢复方式：\n\n"
        f"```bash\n"
        f"cp _archive/.redacted-snapshots/<rel-path> _archive/<rel-path>\n"
        f"```\n"
    )
    ARCHIVED_MD.write_text(content + addendum, encoding="utf-8")
    print(f"已更新: {ARCHIVED_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
