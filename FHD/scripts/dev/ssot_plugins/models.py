"""models 域适配器：FHD/config/models.yaml 为唯一真相源，派生只读副本。

派生目标（全部由本插件 sync 生成、check 验证，禁止手改）：
  - FHD/config/models.generated.json                                   (FHD 运行时)
  - 成都修茈科技有限公司/MODstore_deploy/modstore_server/config/models.generated.json (MODstore 运行时)
  - 成都修茈科技有限公司/MODstore_deploy/market/src/config/modelsGenerated.ts          (前端)

用法：
  python scripts/dev/ssot_plugins/models.py check
  python scripts/dev/ssot_plugins/models.py sync [--apply]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]  # FHD/
REPO_ROOT = ROOT.parent  # 工作树根（含「成都修茈科技有限公司」）
_MOD = REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"

SSOT_YAML = ROOT / "config" / "models.yaml"
FHD_JSON = ROOT / "config" / "models.generated.json"
MOD_JSON = _MOD / "modstore_server" / "config" / "models.generated.json"
FE_TS = _MOD / "market" / "src" / "config" / "modelsGenerated.ts"

_REQUIRED_PROVIDER_FIELDS = (
    "id",
    "label",
    "base_url",
    "dispatch",
    "models_api",
    "gateway_provider",
    "env_keys",
    "default_model",
    "catalog_listed",
    "enabled",
)


# ---------------------------------------------------------------- load / validate
def _load() -> dict[str, Any]:
    with SSOT_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    providers = data.get("providers") or []
    if not providers:
        errors.append("providers 为空")
    seen: set[str] = set()
    alias_owner: dict[str, str] = {}
    for p in providers:
        pid = p.get("id")
        for field in _REQUIRED_PROVIDER_FIELDS:
            if field not in p:
                errors.append(f"provider {pid!r} 缺字段 {field}")
        if pid in seen:
            errors.append(f"provider id 重复: {pid}")
        seen.add(pid)
        for alias in p.get("aliases") or []:
            if alias in alias_owner:
                errors.append(f"别名冲突 {alias}: {alias_owner[alias]} vs {pid}")
            alias_owner[alias] = pid
    # 别名不得与某个真实 id 撞车
    for alias, owner in alias_owner.items():
        if alias in seen:
            errors.append(f"别名 {alias} 与真实 provider id 冲突（owner={owner}）")
    # classification.aggregator_providers 必须是已知 id
    for prov in data.get("classification", {}).get("aggregator_providers", []):
        if prov not in seen:
            errors.append(f"classification.aggregator_providers 含未知 provider: {prov}")
    # known_provider_order 必须等于 catalog_listed 厂商全集（顺序敏感，集合校验）
    order = data.get("known_provider_order") or []
    catalog = {p.get("id") for p in providers if p.get("catalog_listed")}
    if set(order) != catalog:
        miss = catalog - set(order)
        extra = set(order) - catalog
        errors.append(
            f"known_provider_order 与 catalog_listed 不一致 缺={sorted(miss)} 多={sorted(extra)}"
        )
    if len(order) != len(set(order)):
        errors.append("known_provider_order 有重复项")
    # 模态默认价覆盖所有 modalities
    modalities = set(data.get("modalities") or [])
    priced = set((data.get("pricing", {}).get("defaults_by_modality") or {}).keys())
    missing = modalities - priced - {"other"}
    if missing:
        errors.append(f"pricing.defaults_by_modality 缺模态: {sorted(missing)}")
    return errors


# ---------------------------------------------------------------- render
def _render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _render_ts(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    return (
        "/* eslint-disable */\n"
        "// ============================================================\n"
        "// AUTO-GENERATED from FHD/config/models.yaml — DO NOT EDIT.\n"
        "// 重生: python FHD/scripts/dev/ssot_cli.py sync models --apply\n"
        "// 模型/厂商/模态/计费的唯一真相源派生件。\n"
        "// ============================================================\n"
        f"export const MODEL_REGISTRY = {payload} as const;\n\n"
        "export type ModelProvider = (typeof MODEL_REGISTRY.providers)[number];\n"
        "export const MODEL_PROVIDERS = MODEL_REGISTRY.providers;\n"
        "export const MODALITIES = MODEL_REGISTRY.modalities;\n"
        "export const MODALITY_LABELS = MODEL_REGISTRY.modality_labels;\n"
        "export const CHAT_CAPABLE_MODALITIES = MODEL_REGISTRY.chat_capable_modalities;\n"
        "export const CLASSIFICATION_RULES = MODEL_REGISTRY.classification;\n"
        "export const MODEL_PRICING = MODEL_REGISTRY.pricing;\n\n"
        "export function modelProvider(id: string): ModelProvider | undefined {\n"
        "  return MODEL_PROVIDERS.find((p) => p.id === id);\n"
        "}\n\n"
        "export default MODEL_REGISTRY;\n"
    )


def _targets(data: dict[str, Any]) -> list[tuple[Path, str]]:
    js = _render_json(data)
    ts = _render_ts(data)
    return [(FHD_JSON, js), (MOD_JSON, js), (FE_TS, ts)]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- check / sync
def check_drift() -> int:
    if not SSOT_YAML.is_file():
        print(f"models: SSOT 源缺失 {_rel(SSOT_YAML)}", flush=True)
        return 2
    try:
        data = _load()
    except yaml.YAMLError as exc:
        print(f"models: SSOT 解析失败 {exc}", flush=True)
        return 2

    structural = _validate(data)
    if structural:
        print(f"models: SSOT 结构错误 {len(structural)} 项", flush=True)
        for e in structural:
            print(f"  - {e}", flush=True)
        return 2

    errors: list[str] = []
    for path, expected in _targets(data):
        if not path.is_file():
            errors.append(f"派生缺失: {_rel(path)}（跑 sync --apply）")
        elif path.read_text(encoding="utf-8") != expected:
            errors.append(f"派生漂移: {_rel(path)}（跑 sync --apply）")

    if errors:
        print(f"models: {len(errors)} 处漂移", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        return 1

    n_prov = len(data.get("providers") or [])
    print(f"models: OK（{n_prov} 厂商，3 派生件一致）", flush=True)
    return 0


def sync_impl(*, dry_run: bool = True) -> int:
    if not SSOT_YAML.is_file():
        print(f"models: SSOT 源缺失 {_rel(SSOT_YAML)}", flush=True)
        return 2
    try:
        data = _load()
    except yaml.YAMLError as exc:
        print(f"models: SSOT 解析失败 {exc}", flush=True)
        return 2

    structural = _validate(data)
    if structural:
        print(f"models: SSOT 结构错误 {len(structural)} 项，拒绝 sync", flush=True)
        for e in structural:
            print(f"  - {e}", flush=True)
        return 2

    for path, expected in _targets(data):
        same = path.is_file() and path.read_text(encoding="utf-8") == expected
        tag = "无变化" if same else "将写入"
        if dry_run:
            print(f"[dry-run] {tag}: {_rel(path)}", flush=True)
            continue
        if same:
            print(f"[skip] {_rel(path)}", flush=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
        print(f"[write] {_rel(path)}", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        return sync_impl(dry_run=dry_run)
    return 2


if __name__ == "__main__":
    _action = sys.argv[1] if len(sys.argv) > 1 else "check"
    _dry = "--apply" not in sys.argv[2:]
    raise SystemExit(run(_action, {}, dry_run=_dry))
