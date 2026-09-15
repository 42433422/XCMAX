#!/usr/bin/env python3
r"""连接件3 Windows 车道增量：诊断 → 实机故障注入场景复现（复用既有注入脚本）。

Mac 车道 `work_order_repro.py` 覆盖跨平台 module_import 类签名；其余签名产出
`status=needs_scenario` 交人工。本件把 Windows 侧的 needs_scenario 规格**升级**为
可执行的实机复现：确定性映射到 `scripts/package/fault-injection-windows.ps1`
六大场景（kill-all / kill-orphan / corrupt-backup / corrupt-main /
dual-process / migration-mutex），并在隔离 InstallRoot + 隔离 DataRoot 中执行留证。

    python scripts/dev/work_order_repro_windows.py            # 只升级规格（安全）
    python scripts/dev/work_order_repro_windows.py --execute  # 隔离实机复现留证

契约兼容（不改 Mac 任何文件、不改公共 Schema）：
- 读写同一 `test_reports/repro/repro-<key12>.json`：仅当 `kind=none` 或
  `status=needs_scenario` 时重写；module_import 规格原样保留。
- 重写后 `kind=windows_fault_injection`，`scenario` 为 dict（中继/知识回流按
  dict 消费）；执行证据落 `evidence-<key12>.json`（Mac 同命名）。
- 实机安全闸：注入脚本按进程名强杀且 corrupt-backup 写坏备份字节，因此
  DataRoot 落在用户真实 %APPDATA%\XCAGI 时一律拒绝执行（`--execute` 下
  verdict=blocked_by_safety_gate），杜绝误伤客户机。
- fail-open：无规格/无匹配场景只记日志不阻塞；映射为确定性规则，无 LLM。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("work_order_repro_windows")

_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

_DIAGNOSIS_DIR = Path(
    os.environ.get("WORK_ORDER_DIAGNOSIS_DIR") or (_FHD_ROOT / "test_reports" / "diagnosis")
)
_REPRO_DIR = Path(os.environ.get("WORK_ORDER_REPRO_DIR") or (_FHD_ROOT / "test_reports" / "repro"))
_INJECT_SCRIPT = _FHD_ROOT / "scripts" / "package" / "fault-injection-windows.ps1"
_ACCEPT_ROOT = "C:\\XCAGI-acceptance"

# 与 fault-injection-windows.ps1 的 ValidateSet 对齐（公共契约，勿单方改动）。
_SCENARIOS = (
    "kill-all",
    "kill-orphan",
    "corrupt-backup",
    "corrupt-main",
    "dual-process",
    "migration-mutex",
)

# 诊断信号 → 注入场景：确定性关键词映射（命中即定，顺序即优先级）。
_SCENARIO_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "corrupt-main",
        (
            r"corrupt[-_ ]?main",
            r"database.*(malformed|corrupt|not a database)",
            r"integrity.?check",
            r"install_failed",
            r"update_failed",
            r"recover_if_corrupt",
            r"restore.*backup",
        ),
    ),
    (
        "corrupt-backup",
        (
            r"corrupt[-_ ]?backup",
            r"backup.*(fail|error|corrupt|missing)",
            r"备份.*(损坏|失败|不可用)",
        ),
    ),
    (
        "kill-orphan",
        (
            r"orphan",
            r"address already in use",
            r"17500.*(占用|in use|listen)",
            r"port.*conflict",
            r"孤儿",
        ),
    ),
    (
        "dual-process",
        (r"dual.?process", r"single.?instance", r"already running", r"双.*进程", r"重复启动"),
    ),
    (
        "migration-mutex",
        (r"migration.*(race|mutex|lock|concurrent)", r"迁移.*(并发|竞态|锁)", r"alembic.*race"),
    ),
    (
        "kill-all",
        (
            r"kill.?all",
            r"crash",
            r"unexpected.*exit",
            r"health_check_failed",
            r"service_unavailable",
            r"进程.*(崩溃|退出|强杀)",
            r"闪退",
        ),
    ),
)


def _diagnosis_text(record: dict[str, Any]) -> str:
    """诊断记录 → 匹配语料（错误签名/日志节选/原因，小写）。"""
    parts: list[str] = []
    for err in record.get("errors") or []:
        parts.append(str(err.get("message") or ""))
        parts.append(str(err.get("raw") or ""))
        parts.append(str(err.get("code") or ""))
    parts.append(str(record.get("excerpt") or ""))
    parts.append(str(record.get("reason") or ""))
    return "\n".join(parts).lower()


def classify_scenario(record: dict[str, Any]) -> tuple[str, str]:
    """诊断记录 → (注入场景, 命中依据)；无匹配返回 ("", "")。确定性、无 LLM。"""
    text = _diagnosis_text(record)
    if not text.strip():
        return "", ""
    for scenario, patterns in _SCENARIO_RULES:
        for pat in patterns:
            if re.search(pat, text):
                return scenario, pat
    return "", ""


def _is_live_user_data(data_root: Path) -> bool:
    """实机安全闸核心：数据根是否落在用户真实 %APPDATA%\\XCAGI。"""
    appdata = os.environ.get("APPDATA") or ""
    if not appdata:
        return False
    try:
        live = Path(appdata) / "XCAGI"
        return Path(data_root).resolve() == live.resolve()
    except OSError:
        return False


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def upgrade_spec(
    spec: dict[str, Any],
    diagnosis: dict[str, Any],
    *,
    install_root: str,
    data_root: str,
    evidence_dir: str,
) -> dict[str, Any] | None:
    """needs_scenario 规格 → Windows 注入场景规格；不适用/已可执行时返回 None。"""
    if spec.get("kind") not in (None, "", "none") or spec.get("status") not in (
        "needs_scenario",
        "none",
    ):
        return None
    scenario, matched = classify_scenario(diagnosis)
    if not scenario:
        return None
    data_path = Path(data_root)
    live = _is_live_user_data(data_path)
    isolated = not live
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(_INJECT_SCRIPT),
        "-Scenario",
        scenario,
        "-InstallRoot",
        install_root,
        "-DataRoot",
        data_root,
        "-EvidenceDir",
        evidence_dir,
        "-CiMode",
    ]
    spec.update(
        {
            "kind": "windows_fault_injection",
            "status": "generated",
            "upgraded_at": datetime.now(UTC).isoformat(),
            "matched_rule": matched,
            "isolated": isolated,
            "live_data_root_detected": live,
            "scenario": {
                "injection_scenario": scenario,
                "install_root": install_root,
                "data_root": data_root,
                "evidence_dir": evidence_dir,
                "command": command,
                "assertion": "fault-injection receipt summary.fail == 0",
            },
        }
    )
    return spec


def run_injection(spec: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    """隔离实机执行注入脚本，返回红/绿证据；安全闸未过则拒绝。"""
    scenario = spec.get("scenario") or {}
    evidence: dict[str, Any] = {
        "dedup_key": spec.get("dedup_key"),
        "wo_id": spec.get("wo_id"),
        "ran_at": datetime.now(UTC).isoformat(),
        "kind": spec.get("kind"),
        "scenario": scenario.get("injection_scenario"),
        "reproduced": False,
        "exit_code": None,
    }
    if not spec.get("isolated", False):
        evidence["blocked_by_safety_gate"] = True
        evidence["error"] = "data root is live user data or not isolated; execution refused"
        return evidence
    if not _INJECT_SCRIPT.is_file():
        evidence["error"] = "inject_script_missing"
        return evidence
    evidence_dir = str(scenario.get("evidence_dir") or "")
    if not evidence_dir:
        evidence["error"] = "no_evidence_dir"
        return evidence
    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(  # noqa: S603 - 固定参数、隔离目录、无 shell
            list(scenario.get("command") or []),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        evidence["exit_code"] = proc.returncode
        receipt = _load_json(Path(evidence_dir) / "fault-injection-receipt.json")
        evidence["receipt"] = receipt
        # 与 Mac 连接件3 RED/GREEN 语义对齐：
        #   FAIL/PARTIAL = 恢复行为不符合预期 = 客户故障被真实重现（RED，reproduced）
        #   PASS         = 恢复行为符合预期     = 修复后验证通过（GREEN）
        #   SKIP         = 前置不满足（如数据根无备份种子），不算复现，交人工补前置
        target = str(scenario.get("injection_scenario") or "")
        result = next(
            (
                str(s.get("结果") or s.get("scenario_result") or "")
                for s in (receipt or {}).get("scenarios", [])
                if str(s.get("场景") or s.get("scenario") or "").startswith(target)
            ),
            "",
        )
        evidence["scenario_result"] = result
        if result in ("FAIL", "PARTIAL"):
            evidence["reproduced"] = True
            evidence["verdict"] = "red_reproduced"
        elif result == "PASS":
            evidence["reproduced"] = False
            evidence["verdict"] = "green_recovery_ok"
        elif proc.returncode != 0:
            evidence["reproduced"] = True  # 注入脚本自身异常，留人工判读
            evidence["verdict"] = "inject_exit_nonzero"
        else:
            evidence["verdict"] = "skipped_no_seed"
    except subprocess.TimeoutExpired:
        evidence["error"] = f"timeout_{timeout_seconds}s"
    except OSError as exc:
        evidence["error"] = str(exc)[:300]
    return evidence


def run(args: argparse.Namespace) -> int:
    repro_dir = Path(args.repro_dir)
    diag_dir = Path(args.diagnosis_dir)
    specs = sorted(repro_dir.glob("repro-*.json"))
    if not specs:
        logger.info("no repro specs under %s; nothing to upgrade", repro_dir)
        return 0
    upgraded = 0
    for spec_path in specs[: max(0, int(args.max))]:
        key12 = spec_path.name[len("repro-") : -len(".json")]
        spec = _load_json(spec_path)
        if spec is None:
            continue
        diagnosis = _load_json(diag_dir / f"diagnosis-{key12}.json")
        if diagnosis is None:
            logger.info("skip %s: diagnosis file missing", spec_path.name)
            continue
        evidence_dir = str(repro_dir / f"win-evidence-{key12}")
        result = upgrade_spec(
            spec,
            diagnosis,
            install_root=args.install_root,
            data_root=args.data_root or str(Path(args.install_root) / "repro-data"),
            evidence_dir=evidence_dir,
        )
        if result is None:
            logger.info("skip %s: not needs_scenario or no rule match", spec_path.name)
            continue
        spec_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        upgraded += 1
        logger.info(
            "spec upgraded: %s scenario=%s isolated=%s",
            spec_path.name,
            result["scenario"]["injection_scenario"],
            result["isolated"],
        )
        if args.execute:
            evidence = run_injection(result, timeout_seconds=args.timeout)
            ev_path = repro_dir / f"evidence-{key12}.json"
            ev_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(
                "injection run: reproduced=%s exit=%s -> %s",
                evidence.get("reproduced"),
                evidence.get("exit_code"),
                ev_path,
            )
    logger.info("windows repro done: upgraded=%d", upgraded)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repro-dir", default=str(_REPRO_DIR))
    parser.add_argument("--diagnosis-dir", default=str(_DIAGNOSIS_DIR))
    parser.add_argument(
        "--install-root",
        default=_ACCEPT_ROOT,
        help="复现安装根（默认验收专用根 C:\\XCAGI-acceptance）",
    )
    parser.add_argument(
        "--data-root", default="", help="隔离数据根；留空按验收根派生，绝不默认用户 %APPDATA%"
    )
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--execute", action="store_true", help="实机执行（仅隔离数据根通过安全闸时生效）"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
