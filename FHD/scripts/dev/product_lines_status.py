#!/usr/bin/env python3
"""三产品线统一控制面生成器 —— 版本 / 发布状态 / 能力 / 三线成熟度的唯一数字出口。

设计约束（防止再造一个漂移源）：
1. 声明式输入只有 `config/product_lines.yaml`，其中**没有数字**，只有「哪条线包含
   哪些路径 / 能力域 / 发布 SSOT」。
2. 数字全部从既有权威源现算，不复制、不手填、不二次判定：
   - 版本口径        `VERSION.md`（复用 `verify_version_anchors.py` 的解析函数）
   - 各端交付等级    `VERSION.md`（复用 capability-center 的表格解析）
   - 发布火车/清单   `config/release_train.json` · `config/download_release.json`
   - 能力状态        `成都修茈科技有限公司/data/capabilities/catalog.json`
                     （复用 capability-center 的 No Evidence, No Claim 校验器，
                       拒绝第二套状态判定逻辑）
   - 覆盖率          `metrics/coverage-dual-summary.json`
   - Release Gate    `docs/MACOS_RELEASE_SSOT.md` · `docs/WINDOWS_RELEASE_SSOT.md`
3. 生成物两份：
   - `metrics/product_lines_status.generated.json`（机器可读，供 CI / 验收消费）
   - `docs/PRODUCT_LINES_STATUS.md`（人读视图，文件头标 AUTO-GENERATED）
4. `check` 是 CI 漂移门禁：生成物与已提交内容一致 **且** 无阻断级状态漂移。

用法（cwd = `FHD/`）：
    python3 scripts/dev/product_lines_status.py generate
    python3 scripts/dev/product_lines_status.py check
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
FHD_ROOT = HERE.parents[1]
REPO_ROOT = FHD_ROOT.parent
sys.path.insert(0, str(HERE))

from verify_version_anchors import canonical_version, toolchain_version  # noqa: E402

CONFIG_PATH = FHD_ROOT / "config" / "product_lines.yaml"
CAPABILITY_BUILDER = REPO_ROOT / "成都修茈科技有限公司" / "scripts" / "build_capability_center.py"

GATE_STATUSES = {"GREEN", "YELLOW", "RED", "UNKNOWN", "NOT RUN", "NOTRUN"}
_GATE_ROW = re.compile(r"^\|\s*(G\d+)\s*\|([^|]*)\|([^|]*)\|")
_TS_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")
_FOUR_SEGMENT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _product_version_literals(line: str) -> list[str]:
    """行内的四段产品版本字面量；排除 IPv4 / 主机端口这类同形串。"""
    found: list[str] = []
    for match in _FOUR_SEGMENT.finditer(line):
        literal = match.group(0)
        if literal == "0.0.0.0" or any(int(part) > 99 for part in literal.split(".")):
            continue
        before = line[match.start() - 1] if match.start() else ""
        after = line[match.end()] if match.end() < len(line) else ""
        if after in ":/" or before in ":/@":
            continue
        found.append(literal)
    return found


# --------------------------------------------------------------------- 载入

def _load_json(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _capability_builder():
    """载入 capability-center 生成器，复用其证据校验与表格解析。"""
    spec = importlib.util.spec_from_file_location("xcmax_capability_center", CAPABILITY_BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------- Release Gate

def parse_release_gates(rel: str) -> dict:
    """解析平台发布 SSOT 中**首个**「Release Gate 状态」小节的门禁表。

    取首个而不是末个：该小节按「最新版本在前」书写；同一门禁只取首次出现，
    因此得到的是当前版本的门禁结论。未在该表出现的门禁 = 本轮未复测。
    """
    path = REPO_ROOT / rel
    if not path.is_file():
        raise FileNotFoundError(f"missing release SSOT: {rel}")
    text = path.read_text(encoding="utf-8")

    heading, section = None, []
    for line in text.splitlines():
        if heading is None:
            if line.startswith("#") and "Release Gate 状态" in line:
                heading = line.lstrip("# ").strip()
                continue
            continue
        if line.startswith("## "):          # 下一个同级小节 ⇒ 本小节结束
            break
        section.append(line)

    gates: dict[str, str] = {}
    for line in section:
        match = _GATE_ROW.match(line)
        if not match:
            continue
        gate_id = match.group(1)
        status = match.group(3).strip().replace("*", "").replace("`", "").strip().upper()
        if status in GATE_STATUSES and gate_id not in gates:
            gates[gate_id] = status

    return {
        "source": rel,
        "section": heading,
        "gates": gates,
        "summary": _gate_summary(gates),
    }


def _gate_summary(gates: dict[str, str]) -> dict:
    summary = {status: 0 for status in ("GREEN", "YELLOW", "RED", "UNKNOWN")}
    for status in gates.values():
        summary[status] = summary.get(status, 0) + 1
    summary["total"] = len(gates)
    return summary


# ------------------------------------------------------------------- 漂移扫描

def _scan_hardcoded_versions(cfg: dict, product_version: str, errors: list[dict]) -> int:
    """活文档里与 VERSION.md 不一致的四段产品版本 = 硬编码漂移。"""
    allow_markers = cfg.get("version_scan", {}).get("allow_markers", [])
    scanned = 0
    for rel in cfg.get("version_scan", {}).get("files", []):
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(_drift("version-scan-missing", "error", rel, f"扫描清单文件不存在: {rel}"))
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(marker in line for marker in allow_markers):
                continue
            for literal in _product_version_literals(line):
                scanned += 1
                if literal != product_version:
                    errors.append(
                        _drift(
                            "stale-hardcoded-version",
                            "error",
                            f"{rel}:{lineno}",
                            f"写死产品版本 {literal}，VERSION.md 为 {product_version}",
                        )
                    )
    return scanned


def _tracked_files() -> list[str]:
    """git 跟踪文件清单（唯一入账口径；未跟踪/忽略目录天然排除）。"""
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return [p for p in out.stdout.split("\0") if p]


def _scan_mirrors(cfg: dict, items: list[dict]) -> None:
    """已声明镜像：产品版本必须与 canonical 一致，其余运行时字段允许不同。

    级别固定为 info：镜像的存在本身是已知架构事实（见 product_lines.yaml 处置），
    但镜像的 product_version 若与 canonical 分叉，就是版本漂移，必须升级为 error。
    同时反向校验：canonical 之外若出现**未声明**的同名副本，即为新造漂移源，阻断。
    """
    entries = cfg.get("mirrors", [])
    for entry in entries:
        canonical = REPO_ROOT / entry["canonical"]
        mirror = REPO_ROOT / entry["mirror"]
        if not canonical.is_file() or not mirror.is_file():
            items.append(
                _drift(
                    "mirror-missing",
                    "error",
                    entry["mirror"],
                    f"声明的镜像不存在（canonical 存在={canonical.is_file()}，"
                    f"mirror 存在={mirror.is_file()}）：声明已过期，请更新 product_lines.yaml",
                )
            )
            continue
        canonical_version_value = _load_json(entry["canonical"]).get("product_version")
        mirror_version_value = _load_json(entry["mirror"]).get("product_version")
        if canonical_version_value != mirror_version_value:
            items.append(
                _drift(
                    "mirror-version-drift",
                    "error",
                    entry["mirror"],
                    f"镜像 product_version {mirror_version_value} ≠ "
                    f"canonical {canonical_version_value}",
                )
            )
            continue
        items.append(
            _drift(
                "declared-mirror",
                "info",
                entry["mirror"],
                f"已声明镜像（product_version 与 canonical 一致={canonical_version_value}）；"
                f"{entry.get('reason', '')}",
            )
        )

    tracked = _tracked_files()
    for entry in entries:
        allowed = {entry["canonical"], entry["mirror"]}
        name = Path(entry["canonical"]).name
        for path in sorted(t for t in tracked if Path(t).name == name and t not in allowed):
            items.append(
                _drift(
                    "undeclared-duplicate-source",
                    "error",
                    path,
                    f"`{entry['canonical']}` 之外的未声明副本：必然漂移，"
                    f"要么删除，要么在 product_lines.yaml 的 mirrors 中声明",
                )
            )


def _scan_script_version_defaults(cfg: dict, product_version: str, items: list[dict]) -> dict:
    """打包/发布脚本里写死的四段产品版本默认值——应动态读取 VERSION.md。

    每条 pattern 可带 `|级别` 覆盖默认级别：bash 侧（已整改）按 error 阻断；
    PowerShell 侧在另一半改造合并前保持 info（可见不阻断），避免门禁与未合并
    改动交叉打红。按文件聚合，并区分「陈旧」（≠ VERSION.md，真漂移）
    与「仍写死但值正确」（预防性）。
    """
    scan = cfg.get("script_version_scan") or {}
    level = scan.get("level", "info")
    remediation = scan.get("remediation", "动态读取 VERSION.md")
    per_file: list[tuple[str, str, list[str], list[str]]] = []
    for raw in scan.get("patterns", []):
        pattern, _, pat_level = raw.partition("|")
        lvl = pat_level or level
        for rel in sorted(REPO_ROOT.glob(pattern)):
            if not rel.is_file():
                continue
            stale: list[str] = []
            fresh: list[str] = []
            for lineno, line in enumerate(rel.read_text(encoding="utf-8").splitlines(), 1):
                for literal in _product_version_literals(line):
                    (stale if literal != product_version else fresh).append(f"{lineno}→{literal}")
            if stale or fresh:
                per_file.append((lvl, str(rel.relative_to(REPO_ROOT)), stale, fresh))

    for lvl, name, stale, fresh in per_file:
        detail = f"写死产品版本 {len(stale) + len(fresh)} 处（陈旧 {len(stale)} 处"
        if stale:
            detail += "：" + "、".join(stale)
        detail += "）"
        if fresh:
            detail += f"；值正确但仍写死 {len(fresh)} 处，应改为 {remediation}"
        items.append(_drift("hardcoded-script-version", lvl, name, detail))

    return {
        "files": len(per_file),
        "occurrences": sum(len(s) + len(f) for _, _, s, f in per_file),
        "stale": sum(len(s) for _, _, s, _ in per_file),
    }


def _drift(drift_id: str, level: str, source: str, detail: str) -> dict:
    return {"id": drift_id, "level": level, "source": source, "detail": detail}


def detect_drift(cfg: dict, version: dict, train: dict, download: dict) -> tuple[list[dict], dict]:
    """权威源之间的状态漂移。error = 阻断（CI 失败）；info = 需可见但不阻断。

    返回 (漂移清单, 打包脚本硬编码版本普查)。
    """
    product = version["product"]
    toolchain = version["toolchain"]
    items: list[dict] = []

    pairs = [
        ("release_train.product_version", train.get("product_version")),
        ("download_release.marketing_version", download.get("marketing_version")),
    ]
    for name, value in pairs:
        if value != product:
            items.append(
                _drift("version-source-mismatch", "error", name, f"{value} ≠ VERSION.md {product}")
            )

    lock = download.get("version_lock")
    if lock != download.get("download_version"):
        items.append(
            _drift(
                "download-manifest-internal",
                "error",
                "download_release.json",
                f"version_lock={lock} ≠ download_version={download.get('download_version')}",
            )
        )
    if train.get("current") != lock:
        items.append(
            _drift(
                "train-vs-download",
                "error",
                "release_train.current vs download_release.version_lock",
                f"{train.get('current')} ≠ {lock}",
            )
        )

    android = download.get("android_version")
    android_artifact = str(download.get("artifacts", {}).get("enterprise", {}).get("android", ""))
    if android and android not in android_artifact:
        items.append(
            _drift(
                "android-artifact-mismatch",
                "error",
                "download_release.artifacts.enterprise.android",
                f"制品 {android_artifact} 未体现 android_version={android}",
            )
        )

    if lock != product:
        items.append(
            _drift(
                "download-center-lag",
                "info",
                "download_release.version_lock",
                f"下载中心仍为 {lock}，产品版本已是 {product}（发布未闭环则属预期，需保持可见）",
            )
        )
    if download.get("release_ready") is False:
        items.append(
            _drift(
                "release-not-closed",
                "info",
                "download_release.release_ready=false",
                f"{product} 发布面未闭环：下载/更新指针未推进到产品版本",
            )
        )
    if toolchain and not product.startswith(toolchain):
        items.append(
            _drift("toolchain-mapping", "error", "VERSION.md", f"工具链映射 {toolchain} 不是 {product} 的等价三段")
        )

    _scan_hardcoded_versions(cfg, product, items)
    _scan_mirrors(cfg, items)
    census = _scan_script_version_defaults(cfg, product, items)
    return items, census


# ---------------------------------------------------------------- 控制面组装

def build_status() -> dict:
    cfg = load_config()
    version = {"product": canonical_version(), "toolchain": toolchain_version(), "source": cfg["sources"]["version"]}
    train = _load_json(cfg["sources"]["release_train"])
    download = _load_json(cfg["sources"]["download_release"])
    coverage = _load_json(cfg["sources"]["coverage"])

    builder = _capability_builder()
    cap_data, cap_warnings, domains_full = builder.build()
    cap_by_domain = {d["id"]: d for d in domains_full}

    assigned: set[str] = set()
    lines = []
    for line in cfg["lines"]:
        feature_status: dict[str, int] = {}
        total = 0
        for domain_id in line["capability_domains"]:
            assigned.add(domain_id)
            domain = cap_by_domain.get(domain_id)
            if domain is None:
                continue
            for module in domain["modules"]:
                for feature in module["features"]:
                    total += 1
                    feature_status[feature["status"]] = feature_status.get(feature["status"], 0) + 1

        releases = {}
        for platform, doc in (line.get("releases") or {}).items():
            releases[platform] = (
                parse_release_gates(doc) if doc.endswith("RELEASE_SSOT.md") else {"source": doc}
            )

        lines.append(
            {
                "id": line["id"],
                "name": line["name"],
                "priority": line["priority"],
                "role": line["role"],
                "paths": line["paths"],
                "paths_ok": all((REPO_ROOT / p).exists() for p in line["paths"]),
                "entry": line.get("entry"),
                "entry_ok": bool(line.get("entry")) and (REPO_ROOT / line["entry"]).exists(),
                "workflows": line.get("workflows", []),
                "capability": {
                    "domains": line["capability_domains"],
                    "total": total,
                    "by_status": feature_status,
                    "verified": feature_status.get("verified", 0),
                },
                "releases": releases,
            }
        )

    unassigned = sorted(set(cap_by_domain) - assigned)
    drift, census = detect_drift(cfg, version, train, download)

    return {
        "schema": "xcagi.product_lines_status/v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "generator": "FHD/scripts/dev/product_lines_status.py",
        "config": str(CONFIG_PATH.relative_to(REPO_ROOT)),
        "policy": (
            "本文件为生成物：版本/发布/能力/覆盖率的数字全部取自各自权威源，"
            "禁止手改；三线「成熟度」只呈现能力目录自有的证据分级计数与 Release Gate 结论，"
            "不合成任何自造评分。"
        ),
        "version": version,
        "release": {
            "train": {
                "epoch": train.get("epoch"),
                "product_version": train.get("product_version"),
                "current": train.get("current"),
                "day_index": train.get("day_index"),
                "last_bump_at": train.get("last_bump_at"),
            },
            "download": {
                "version_lock": download.get("version_lock"),
                "download_version": download.get("download_version"),
                "marketing_version": download.get("marketing_version"),
                "android_version": download.get("android_version"),
                "release_ready": download.get("release_ready"),
                "channel_release_ready": download.get("channel_release_ready"),
                "active_skus": download.get("active_skus", []),
                "frozen_skus": download.get("frozen_skus", []),
                "artifacts": download.get("artifacts", {}),
                "channels": download.get("channels", {}),
            },
        },
        "platform_levels": builder.load_platform_levels(),
        "coverage": {
            "source": cfg["sources"]["coverage"],
            "committed_head": coverage.get("committed_head", {}),
            "ratchet_floors": coverage.get("ratchet_floors", {}),
            "quality_gate": coverage.get("quality_gate", {}),
        },
        "capability_totals": cap_data["stats"],
        "capability_warnings": cap_warnings,
        "capability_domains_unassigned": unassigned,
        "lines": lines,
        "drift": drift,
        "drift_summary": {
            "error": sum(1 for d in drift if d["level"] == "error"),
            "info": sum(1 for d in drift if d["level"] == "info"),
        },
        "script_hardcode_census": census,
    }


# ------------------------------------------------------------------- 渲染

def render_doc(status: dict) -> str:
    version = status["version"]
    train = status["release"]["train"]
    download = status["release"]["download"]
    coverage = status["coverage"]
    head = coverage["committed_head"]
    floors = coverage["ratchet_floors"]
    stats = status["capability_totals"]
    by_status = stats["by_status"]

    out: list[str] = []
    out.append("# 三产品线统一控制面（自动生成）")
    out.append("")
    out.append("<!-- AUTO-GENERATED by FHD/scripts/dev/product_lines_status.py —— 禁止手改。")
    out.append("     声明式输入：FHD/config/product_lines.yaml；本域登记在 FHD/config/ssot.yaml。")
    out.append("     数字漂移由 CI（ssot_cli.py gate → product-lines 域）阻断。 -->")
    out.append("")
    out.append(f"> 生成时间：{status['generated_at']} ｜ 生成器：`{status['generator']}`")
    out.append("")
    out.append(
        "> 本文件是 XCMAX 三产品线状态（版本 / 发布 / 能力 / 三线成熟度）的**单一事实来源**，"
        "全部数字自动生成，禁止手改；任何文档引用这些数字都应指向本文件或原始权威源。"
    )
    out.append("")
    out.append(status["policy"])
    out.append("")
    out.append("## 1. 版本口径（唯一出口：`FHD/VERSION.md`）")
    out.append("")
    out.append("| 口径 | 值 | 来源 |")
    out.append("|------|----|------|")
    out.append(f"| 稳定产品版本 | `{version['product']}` | `{version['source']}` |")
    out.append(f"| 工具链兼容版本 | `{version['toolchain']}` | `{version['source']}` |")
    out.append(f"| 发布火车 product_version | `{train['product_version']}` | `release_train.json` |")
    out.append(f"| 发布火车 current | `{train['current']}` | `release_train.json` |")
    out.append(f"| 下载清单 version_lock | `{download['version_lock']}` | `download_release.json` |")
    out.append(f"| 下载清单 download_version | `{download['download_version']}` | `download_release.json` |")
    out.append(f"| 下载清单 marketing_version | `{download['marketing_version']}` | `download_release.json` |")
    out.append(f"| Android 版本 | `{download['android_version']}` | `download_release.json` |")
    out.append(f"| release_ready | `{json.dumps(download['release_ready'])}` | `download_release.json` |")
    out.append(f"| 活跃 / 冻结 SKU | `{','.join(download['active_skus']) or '—'}` / `{','.join(download['frozen_skus']) or '—'}` | `download_release.json` |")
    out.append("")
    out.append("## 2. 状态漂移（控制面判定）")
    out.append("")
    summary = status["drift_summary"]
    out.append(f"阻断级漂移 **{summary['error']}** 项，需可见但不阻断 **{summary['info']}** 项。")
    out.append("")
    census = status["script_hardcode_census"]
    if census["files"]:
        out.append(
            f"> 其中打包/发布脚本写死产品版本的普查：**{census['files']} 个文件 / "
            f"{census['occurrences']} 处**（陈旧 {census['stale']} 处）。"
            f"bash 侧已整改并按阻断跟踪；PowerShell 侧在 Windows 侧改造合并前"
            f"按「可见但不阻断」跟踪，逐文件明细见下表。"
        )
        out.append("")
    if status["drift"]:
        out.append("| 级别 | 来源 | 事实 |")
        out.append("|------|------|------|")
        for item in status["drift"]:
            level = "**阻断**" if item["level"] == "error" else "可见"
            out.append(f"| {level} | `{item['source']}` | {item['detail']} |")
    else:
        out.append("未发现漂移。")
    out.append("")
    out.append("## 3. 三线成熟度（只列能力目录自有的证据分级计数 + Release Gate 结论）")
    out.append("")
    out.append("> 本节不合成任何自造评分。能力计数来自能力目录 `No Evidence, No Claim` 校验后的状态；")
    out.append("> Gate 结论来自平台发布 SSOT 的当前版本小节；未在该小节复测的门禁记「本轮未复测」，不推断。")
    out.append("")
    out.append("### 3.1 三线总览")
    out.append("")
    out.append("| 产品线 | 优先级 | 定位 | 能力（已验证/总数） | 状态分布 | 平台门禁 | 入口可达 |")
    out.append("|--------|--------|------|---------------------|----------|----------|----------|")
    for line in status["lines"]:
        cap = line["capability"]
        distribution = " / ".join(
            f"{key} {cap['by_status'].get(key, 0)}"
            for key in ("verified", "partial", "implemented", "planned")
        )
        gate_cells = []
        for platform, gate in line["releases"].items():
            if "summary" in gate:
                gs = gate["summary"]
                gate_cells.append(
                    f"{platform}: GREEN {gs['GREEN']} / YELLOW {gs['YELLOW']} / RED {gs['RED']} / 未复测 {gs['UNKNOWN']}"
                )
        out.append(
            f"| **{line['name']}** | {line['priority']} | {line['role']} | "
            f"{cap['verified']}/{cap['total']} | {distribution} | "
            f"{'；'.join(gate_cells) or '—'} | {'是' if line['entry_ok'] else '**否**'} |"
        )
    out.append("")
    out.append("### 3.2 各线明细")
    out.append("")
    for line in status["lines"]:
        out.append(f"#### {line['name']}（`{line['id']}` · {line['priority']} · {line['role']}）")
        out.append("")
        out.append(f"- 代码路径：{'、'.join(f'`{p}`' for p in line['paths'])}（存在：{'是' if line['paths_ok'] else '否'}）")
        out.append(f"- 日常入口：`{line['entry']}`（存在：{'是' if line['entry_ok'] else '否'}）")
        out.append(f"- 能力域：{'、'.join(f'`{d}`' for d in line['capability']['domains'])}")
        out.append(f"- CI 主 workflow：{'、'.join(f'`{w}`' for w in line['workflows']) or '—'}")
        for platform, gate in line["releases"].items():
            if "gates" not in gate:
                continue
            out.append(
                f"- {platform} Release Gate（来源 `{gate['source']}`，小节「{gate['section']}」）："
                + "、".join(f"{gid} {st}" for gid, st in sorted(gate["gates"].items()))
            )
        out.append("")
    if status["capability_domains_unassigned"]:
        out.append(
            "> ⚠ 未划归任何产品线的能力域："
            + "、".join(f"`{d}`" for d in status["capability_domains_unassigned"])
        )
        out.append("")
    out.append("## 4. 能力目录汇总（`capability-center` 域）")
    out.append("")
    out.append(f"共 {stats['total']} 项能力 / {stats['modules']} 模块 / {stats['domains']} 域；"
               f"已验证 {by_status['verified']}、部分验证 {by_status['partial']}、"
               f"已实现待验证 {by_status['implemented']}、规划中 {by_status['planned']}。")
    out.append("")
    out.append("| 平台 | 覆盖能力数 |")
    out.append("|------|-----------|")
    for platform, count in sorted(stats.get("platform_counts", {}).items()):
        out.append(f"| {platform} | {count} |")
    out.append("")
    out.append("## 5. 各端交付等级（对外口径，读自 `FHD/VERSION.md`）")
    out.append("")
    if status["platform_levels"]:
        out.append("| 端 | 等级 |")
        out.append("|----|------|")
        for name, level in status["platform_levels"].items():
            out.append(f"| {name} | {level} |")
    else:
        out.append("VERSION.md 未提供「各端交付等级」表。")
    out.append("")
    out.append("## 6. 覆盖率（`coverage` 域，唯一数字源）")
    out.append("")
    out.append(
        f"后端行 {head.get('backend_line_pct')}% / 分支 {head.get('backend_branch_pct')}%；"
        f"前端行 {head.get('frontend_line_pct')}% / 分支 {head.get('frontend_branch_pct')}%"
        f"（提交态 {head.get('commit')}，采集于 {head.get('captured_at')}）。"
    )
    out.append("")
    out.append(f"棘轮 floor：后端行 {floors.get('backend_line')} / 分支 {floors.get('backend_branch')}；"
               f"前端行 {floors.get('frontend_lines')} / 分支 {floors.get('frontend_branches')}。"
               f"门禁结论：{coverage['quality_gate'].get('status')}。")
    out.append("")
    out.append("任何文档引用覆盖率必须引用本表或 `FHD/metrics/coverage-dual-summary.json`，不得另抄一份数字。")
    out.append("")
    return "\n".join(out)


def render_json(status: dict) -> str:
    return json.dumps(status, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------- main

def generate() -> int:
    cfg = load_config()
    status = build_status()
    targets = {
        REPO_ROOT / cfg["generated"]["json"]: render_json(status),
        REPO_ROOT / cfg["generated"]["doc"]: render_doc(status),
    }
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"已生成 {path.relative_to(REPO_ROOT)}")

    for item in status["drift"]:
        print(f"  [{item['level']}] {item['source']}: {item['detail']}")
    print(
        f"漂移：阻断 {status['drift_summary']['error']} 项 / 可见 {status['drift_summary']['info']} 项"
    )
    return 0


def check() -> int:
    cfg = load_config()
    status = build_status()
    failures: list[str] = []

    for rel, expected in (
        (cfg["generated"]["json"], render_json(status)),
        (cfg["generated"]["doc"], render_doc(status)),
    ):
        path = REPO_ROOT / rel
        if not path.is_file():
            failures.append(f"缺失生成物：{rel}（运行 python3 scripts/dev/product_lines_status.py generate）")
            continue
        actual = _TS_PATTERN.sub("BUILD-TIME", path.read_text(encoding="utf-8"))
        if actual != _TS_PATTERN.sub("BUILD-TIME", expected):
            failures.append(f"生成物与权威源漂移：{rel}")

    for item in status["drift"]:
        if item["level"] == "error":
            failures.append(f"阻断级漂移 [{item['id']}] {item['source']}：{item['detail']}")

    for item in status["drift"]:
        if item["level"] != "error":
            print(f"INFO [{item['id']}] {item['source']}: {item['detail']}")

    if failures:
        print("产品线控制面门禁失败：", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        "产品线控制面校验通过："
        f"product={status['version']['product']}，"
        f"{len(status['lines'])} 条主线，"
        f"能力 {status['capability_totals']['total']} 项，"
        f"阻断级漂移 0 项。"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="三产品线统一控制面生成器")
    parser.add_argument("command", choices=("generate", "check"))
    args = parser.parse_args()
    return generate() if args.command == "generate" else check()


if __name__ == "__main__":
    raise SystemExit(main())