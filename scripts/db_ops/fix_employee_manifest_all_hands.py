#!/usr/bin/env python3
"""修复编制员工包 manifest / yuangon：behavior_rules、identity、handlers、全员大会待机、生态业务字段。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
EMP_ROOT = REPO / "mods" / "_employees"
YUANGON_ROOT = REPO.parent / "成都修茈科技有限公司" / "yuangon"

STANDARD_RULES = [
    "始终围绕{role}的职责范围处理请求。",
    "优先使用 input 中提供的 manifest_signals / role_context / yuangon 节选作答；缺口用「待确认」标注，不要补造缺失事实。",
    "当输入不足、工具失败或结论不确定时，明确说明原因和需要补充的信息。",
    "输出保持结构化、可执行，避免泛泛而谈。",
]

CRAFT_WORKSHOP_IDS = frozenset(
    {
        "intent-analyst",
        "employee-planner",
        "artifact-generator",
        "quality-validator",
        "miniapp-builder",
        "script-binder",
        "workflow-automator",
        "pack-registrar",
        "sandbox-tester",
        "code-validator",
        "self-checker",
        "host-checker",
        "hex-quality-assessor",
    }
)

STANDBY_RULE = (
    "全员大会（input.all_hands_standby 为 true）时只汇报职责与待机条件，"
    "不声称已执行需上游产物（员工包、workflow_id、产物路径）的流水线步骤；"
    "就绪后说明等待的上游岗位与输入形态。"
)

ECOSYSTEM_BUSINESS: dict[str, dict[str, Any]] = {
    "ecosystem-partner-onboard-officer": {
        "five_line": "O-B",
        "subzone": "partner-onboard",
        "kpis": ["伙伴建档 SLA", "租户隔离校验通过率"],
    },
    "ecosystem-joint-catalog-officer": {
        "five_line": "O-B",
        "subzone": "joint-catalog",
        "kpis": ["联合目录一致性", "上架 gate 通过率"],
    },
    "ecosystem-delivery-reporter": {
        "five_line": "O-B",
        "subzone": "delivery-report",
        "kpis": ["交付报告准时率", "客户可见状态准确率"],
    },
    "ecosystem-investor-portal-officer": {
        "five_line": "O-B",
        "subzone": "investor-portal",
        "kpis": ["投资人门户可用性", "披露材料完整性"],
    },
    "ecosystem-revenue-share-reconciler": {
        "five_line": "O-B",
        "subzone": "revenue-share",
        "kpis": ["分账对账差异率", "结算批次闭环率"],
    },
}

CI_COVERAGE_ARTIFACTS = {
    "test-qa-runner": [
        "coverage/**",
        "MODstore_deploy/.coverage",
        "MODstore_deploy/.pytest_cache/**",
        "vibe-coding/.pytest_cache/**",
        "playwright-report/**",
        "test-results/**",
        ".github/workflows/ci-*.yml",
    ],
    "log-monitor-incident": [
        "coverage/**",
        "playwright-report/**",
        "test-results/**",
        "MODstore_deploy/.coverage",
        "MODstore_deploy/.pytest_cache/**",
    ],
}


def _yuangon_yaml_path(pkg_id: str) -> Path | None:
    if not YUANGON_ROOT.is_dir():
        return None
    for yaml_path in YUANGON_ROOT.glob(f"*/{pkg_id}/employee.yaml"):
        return yaml_path
    return None


def _load_yuangon_meta(pkg_id: str) -> dict:
    yaml_path = _yuangon_yaml_path(pkg_id)
    if not yaml_path:
        return {}
    try:
        import yaml

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _default_handlers() -> list[str]:
    return ["llm_md", "echo"]


def _handlers_from_yuangon(yg: dict) -> list[str]:
    actions = yg.get("actions")
    if isinstance(actions, dict):
        raw = actions.get("handlers")
        if isinstance(raw, list) and raw:
            return [str(h).strip() for h in raw if str(h).strip()]
    return _default_handlers()


def _sync_manifest_actions(v2: dict, yg: dict) -> bool:
    handlers = _handlers_from_yuangon(yg)
    actions = v2.setdefault("actions", {})
    if not isinstance(actions, dict):
        return False
    changed = False
    if actions.get("handlers") != handlers:
        actions["handlers"] = handlers
        changed = True
    if "direct_python" not in handlers and "direct_python" in actions:
        del actions["direct_python"]
        changed = True
    yg_actions = yg.get("actions") if isinstance(yg.get("actions"), dict) else {}
    for key in ("shell_exec", "ssh_exec", "agent", "webhook", "doc_sync"):
        if key in yg_actions and actions.get(key) != yg_actions.get(key):
            actions[key] = yg_actions[key]
            changed = True
    return changed


def fix_yuangon_yaml(pkg_id: str, yg_path: Path, yg: dict) -> bool:
    import yaml

    changed = False
    if pkg_id in CRAFT_WORKSHOP_IDS:
        ah = yg.setdefault("all_hands", {})
        if isinstance(ah, dict):
            if ah.get("standby") is not True:
                ah["standby"] = True
                changed = True
            runbook = (
                "制作车间流水线岗位：无上游员工包/workflow/产物路径时仅汇报职责边界与待机条件；"
                "收到 intent-analyst 或 pack-registrar 输入后再描述可执行步骤。"
            )
            if str(ah.get("runbook") or "").strip() != runbook:
                ah["runbook"] = runbook
                changed = True
    if pkg_id in ECOSYSTEM_BUSINESS:
        biz = ECOSYSTEM_BUSINESS[pkg_id]
        bc = yg.setdefault("business_context", {})
        if isinstance(bc, dict):
            for k, v in biz.items():
                if bc.get(k) != v:
                    bc[k] = v
                    changed = True
            if not str(bc.get("summary") or "").strip():
                bc["summary"] = str(yg.get("domain") or "").strip()
                changed = True
    ci_paths = CI_COVERAGE_ARTIFACTS.get(pkg_id)
    if ci_paths:
        existing = yg.get("ci_coverage_artifacts")
        if existing != ci_paths:
            yg["ci_coverage_artifacts"] = ci_paths
            changed = True
    if changed:
        yg_path.write_text(
            yaml.safe_dump(yg, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    return changed


def _needs_behavior_rules_fix(rules: list) -> bool:
    for rule in rules:
        text = str(rule or "")
        if len(text) > 120:
            return True
        if "优先使用用户提供的上下文完成" in text and len(text) > 80:
            return True
    return False


def fix_manifest(path: Path) -> bool:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict) or manifest.get("artifact") != "employee_pack":
        return False

    pkg_id = str(manifest.get("id") or path.parent.name).strip()
    yg = _load_yuangon_meta(pkg_id)
    changed = False

    v2 = manifest.setdefault("employee_config_v2", {})
    if not isinstance(v2, dict):
        return False
    ident = v2.setdefault("identity", {})
    if isinstance(ident, dict):
        for key in ("owner", "area", "domain"):
            val = yg.get(key)
            if val and not str(ident.get(key) or "").strip():
                ident[key] = str(val).strip()
                changed = True

    cog = v2.setdefault("cognition", {})
    agent = cog.setdefault("agent", {}) if isinstance(cog, dict) else {}
    role = agent.setdefault("role", {}) if isinstance(agent, dict) else {}
    label = str(role.get("name") or ident.get("name") or manifest.get("name") or pkg_id).strip()

    rules = agent.get("behavior_rules") if isinstance(agent, dict) else None
    if not isinstance(rules, list) or _needs_behavior_rules_fix(rules):
        if isinstance(agent, dict):
            agent["behavior_rules"] = [r.format(role=label) for r in STANDARD_RULES]
            changed = True

    skills = cog.get("skills") if isinstance(cog, dict) else None
    if isinstance(skills, list):
        for sk in skills:
            if not isinstance(sk, dict):
                continue
            brief = str(sk.get("brief") or "")
            if brief.endswith("合并到") or (len(brief) > 140 and not brief.endswith("。")):
                name = str(sk.get("name") or "").strip()
                sk["brief"] = f"{name}：服务于本岗位职责的结构化输出与校验。"[:120]
                changed = True

    if _sync_manifest_actions(v2, yg):
        changed = True

    if isinstance(agent, dict):
        rules = agent.get("behavior_rules")
        if not isinstance(rules, list):
            rules = []
        if pkg_id in CRAFT_WORKSHOP_IDS and STANDBY_RULE not in rules:
            agent["behavior_rules"] = list(rules) + [STANDBY_RULE]
            changed = True

    meta = v2.setdefault("metadata", {})
    if isinstance(meta, dict) and pkg_id in CRAFT_WORKSHOP_IDS:
        if meta.get("all_hands_standby") is not True:
            meta["all_hands_standby"] = True
            changed = True

    if pkg_id in CI_COVERAGE_ARTIFACTS:
        sig = v2.setdefault("manifest_signals", {})
        if isinstance(sig, dict):
            if sig.get("ci_coverage_artifacts") != CI_COVERAGE_ARTIFACTS[pkg_id]:
                sig["ci_coverage_artifacts"] = CI_COVERAGE_ARTIFACTS[pkg_id]
                changed = True

    if changed:
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    if not EMP_ROOT.is_dir():
        print(f"employee root missing: {EMP_ROOT}", file=sys.stderr)
        return 1
    fixed_mf = fixed_yg = 0
    for mf in sorted(EMP_ROOT.glob("*/manifest.json")):
        pkg_id = mf.parent.name
        yg_path = _yuangon_yaml_path(pkg_id)
        if yg_path:
            yg = _load_yuangon_meta(pkg_id)
            if yg and fix_yuangon_yaml(pkg_id, yg_path, yg):
                fixed_yg += 1
                print(f"fixed yuangon {yg_path.relative_to(REPO.parent)}")
        if fix_manifest(mf):
            fixed_mf += 1
            print(f"fixed {mf.relative_to(REPO)}")
    print(f"done: {fixed_mf} manifest(s), {fixed_yg} yuangon employee.yaml updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
