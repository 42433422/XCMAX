"""account-system 域适配器：校验产品端/账号/行业/Persona SSOT 一致性。"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT, load_registry  # noqa: E402


def _load_account_tier_module():
    """Load the leaf module without importing app.application.__init__."""
    path = _FHD_ROOT / "app" / "application" / "account_tier_derivation.py"
    spec = importlib.util.spec_from_file_location("_account_tier_derivation_ssot", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ACCOUNT_TIER = _load_account_tier_module()
BUDGET_RANGES = _ACCOUNT_TIER.BUDGET_RANGES
derive_account_tier = _ACCOUNT_TIER.derive_account_tier

ACCOUNT_DOC = ROOT / "docs" / "account_system_ssot.md"
SSOT_INDEX = ROOT / "docs" / "SSOT_INDEX.md"
SAAS_PLANS = ROOT / "config" / "saas_plans.json"
INDUSTRY_PRESETS = ROOT / "config" / "industry_presets.json"
INDUSTRY_BASELINE = ROOT / "config" / "industry_baseline.json"
INDUSTRY_ALIASES = ROOT / "config" / "industry_mod_aliases.json"
REGISTER_VIEW = ROOT / "frontend" / "src" / "views" / "RegisterView.vue"
ADMIN_VIEW = ROOT / "frontend" / "src" / "views" / "AdminEntitlementsView.vue"
AUTH_API = ROOT / "frontend" / "src" / "api" / "auth.ts"

EXPECTED_BUDGETS = ("1–5 万", "5–10 万", "10–50 万", "50–100 万")
EXPECTED_BUDGET_TO_TIER = {
    "1–5 万": "normal",
    "5–10 万": "pro",
    "10–50 万": "max",
    "50–100 万": "ultra",
}
LEGACY_BUDGETS = ("5 万以内", "5–20 万", "20–50 万", "50 万以上")
EXPECTED_PRESET_IDS = ("通用", "涂料", "考勤", "批发", "电商", "餐饮", "物流", "管理端")
REGISTERABLE_INDUSTRIES = tuple(i for i in EXPECTED_PRESET_IDS if i != "管理端")
REQUIRED_DOC_SNIPPETS = (
    "## 零、产品端与分发矩阵",
    "## 一、四维真相源",
    "### 2.6 账号类型总表",
    "### 2.7 管理账号体系",
    "### 2.8 行业体系",
    "### 2.9 人格体系",
    "RBAC/租户隔离 > 账号类型 > 行业授权 > 档位/VIP > 端能力 > 任务偏好",
)


def _read_text(path: Path, errors: list[str]) -> str:
    if not path.is_file():
        errors.append(f"缺少文件: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"缺少 JSON: {path.relative_to(ROOT)}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.relative_to(ROOT)} JSON 无效: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.relative_to(ROOT)} 顶层必须是 object")
        return {}
    return data


def _plan_by_id(plans: list[dict[str, Any]], plan_id: str) -> dict[str, Any] | None:
    for plan in plans:
        if plan.get("id") == plan_id:
            return plan
    return None


def _check_registry(errors: list[str]) -> None:
    domains = load_registry()
    domain = next((d for d in domains if d.get("name") == "account-system"), None)
    if not domain:
        errors.append("config/ssot.yaml 未登记 account-system 域")
        return
    if domain.get("ssot") != "FHD/docs/account_system_ssot.md":
        errors.append("account-system.ssot 必须指向 FHD/docs/account_system_ssot.md")
    if "account_system.py check" not in str(domain.get("check") or ""):
        errors.append("account-system.check 必须调用 account_system.py check")


def _check_doc(errors: list[str]) -> None:
    text = _read_text(ACCOUNT_DOC, errors)
    if not text:
        return
    for snippet in REQUIRED_DOC_SNIPPETS:
        if snippet not in text:
            errors.append(f"account_system_ssot.md 缺少片段: {snippet}")
    index_text = _read_text(SSOT_INDEX, errors)
    if "account_system_ssot.md" not in index_text:
        errors.append("SSOT_INDEX.md 未登记 account_system_ssot.md")


def _check_budgets(errors: list[str]) -> None:
    if tuple(BUDGET_RANGES) != EXPECTED_BUDGETS:
        errors.append(f"BUDGET_RANGES={BUDGET_RANGES!r}，应为 {EXPECTED_BUDGETS!r}")
    for budget, tier in EXPECTED_BUDGET_TO_TIER.items():
        got = derive_account_tier(budget)
        if got != tier:
            errors.append(f"derive_account_tier({budget!r})={got!r}，应为 {tier!r}")

    cfg = _load_json(SAAS_PLANS, errors)
    mapping = cfg.get("budget_permanent_map")
    if not isinstance(mapping, dict):
        errors.append("saas_plans.json 缺少 budget_permanent_map")
        mapping = {}
    for budget in EXPECTED_BUDGETS:
        if budget not in mapping:
            errors.append(f"budget_permanent_map 缺少新档位 {budget}")
    for budget in LEGACY_BUDGETS:
        if budget not in mapping:
            errors.append(f"budget_permanent_map 缺少旧档位兼容 {budget}")

    plans_raw = cfg.get("plans") or []
    plans = [p for p in plans_raw if isinstance(p, dict)]
    trial = _plan_by_id(plans, "saas-trial-30")
    if not trial:
        errors.append("saas_plans.json 缺少 saas-trial-30")
    else:
        expected_trial = {
            "amount_cents": 9900,
            "quota_cents": 10000,
            "duration_days": 30,
            "license_type": "trial",
            "expires_behavior": "freeze",
            "account_tier": "normal",
        }
        for key, expected in expected_trial.items():
            if trial.get(key) != expected:
                errors.append(f"saas-trial-30.{key}={trial.get(key)!r}，应为 {expected!r}")

    front_files = (REGISTER_VIEW, ADMIN_VIEW, AUTH_API)
    budget_pattern = re.compile("|".join(re.escape(b) for b in EXPECTED_BUDGETS))
    for path in front_files:
        text = _read_text(path, errors)
        if not text:
            continue
        found = set(budget_pattern.findall(text))
        missing = set(EXPECTED_BUDGETS) - found
        if missing:
            errors.append(f"{path.relative_to(ROOT)} 缺少前端新档位: {sorted(missing)}")
        leaked_legacy = [b for b in LEGACY_BUDGETS if b in text]
        if leaked_legacy:
            errors.append(f"{path.relative_to(ROOT)} 前端仍展示旧档位: {leaked_legacy}")


def _check_industries(errors: list[str]) -> None:
    presets = _load_json(INDUSTRY_PRESETS, errors)
    baseline = _load_json(INDUSTRY_BASELINE, errors)
    _load_json(INDUSTRY_ALIASES, errors)

    preset_ids = tuple(presets.get("preset_ids") or ())
    if preset_ids != EXPECTED_PRESET_IDS:
        errors.append(f"industry_presets.preset_ids={preset_ids!r}，应为 {EXPECTED_PRESET_IDS!r}")

    preset_map = presets.get("presets") or {}
    if not isinstance(preset_map, dict):
        errors.append("industry_presets.presets 必须是 object")
        preset_map = {}
    for industry_id in EXPECTED_PRESET_IDS:
        item = preset_map.get(industry_id)
        if not isinstance(item, dict):
            errors.append(f"industry_presets.presets 缺少 {industry_id}")
            continue
        for key in ("id", "name", "scenario", "welcomeIntro", "quickButtons", "uiLabels"):
            if key not in item:
                errors.append(f"industry_presets.{industry_id} 缺少 {key}")

    open_ids = baseline.get("onboarding_open_industry_ids") or []
    if not isinstance(open_ids, list):
        errors.append("industry_baseline.onboarding_open_industry_ids 必须是 list")
        open_ids = []
    for industry_id in open_ids:
        if industry_id not in REGISTERABLE_INDUSTRIES:
            errors.append(f"开放行业 {industry_id!r} 不在企业可注册行业内")

    packages = baseline.get("industry_packages") or {}
    if not isinstance(packages, dict):
        errors.append("industry_baseline.industry_packages 必须是 object")
        packages = {}
    for industry_id in open_ids:
        item = packages.get(industry_id)
        if not isinstance(item, dict) or not item.get("mod_id"):
            errors.append(f"开放行业 {industry_id} 缺少 industry_packages.{industry_id}.mod_id")

    industries = baseline.get("industries") or {}
    if not isinstance(industries, dict):
        errors.append("industry_baseline.industries 必须是 object")
        industries = {}
    for industry_id in REGISTERABLE_INDUSTRIES:
        if industry_id not in industries:
            errors.append(f"industry_baseline.industries 缺少 {industry_id}")


def check_drift() -> int:
    errors: list[str] = []
    _check_registry(errors)
    _check_doc(errors)
    _check_budgets(errors)
    _check_industries(errors)

    if errors:
        print(f"account-system: {len(errors)} 处漂移", flush=True)
        for error in errors[:50]:
            print(f"  - {error}", flush=True)
        if len(errors) > 50:
            print(f"  ... 还有 {len(errors) - 50} 条", flush=True)
        return 1
    print("account-system: OK（产品端/账号/行业/Persona SSOT 一致）", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("account-system: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
