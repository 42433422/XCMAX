# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def resolve_llm_provider_model(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    返回 (provider, model, error_message)。
    若 body 未传 provider/model，则读用户 default_llm_json。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        return (prov, mdl, None)
    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    prov = str(prefs.get("provider") or "").strip()
    mdl = str(prefs.get("model") or "").strip()
    if not prov or prov not in _facade().KNOWN_PROVIDERS or (not mdl):
        return (
            None,
            None,
            "请先在 LLM 设置中选择默认供应商与模型，或在请求中传入 provider 与 model",
        )
    return (prov, mdl, None)


async def resolve_llm_provider_model_auto(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    工作台 Auto 语义：显式 provider/model 必须可用；否则优先账户默认，
    默认无 key 时自动切到第一个有 key 且能拿到模型目录的供应商。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        api_key, _ = _facade().resolve_api_key(db, user.id, prov)
        if not api_key:
            return (None, None, f"供应商 {prov} 未配置可用 API Key")
        return (prov, mdl, None)
    from modstore_server.llm_catalog import get_models_for_provider

    async def first_model_id(p: str) -> str:
        try:
            block = await get_models_for_provider(db, user.id, p, force_refresh=False)
        except RECOVERABLE_ERRORS:
            return ""
        mids = list(block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    pref_p = str(prefs.get("provider") or "").strip()
    pref_m = str(prefs.get("model") or "").strip()
    if pref_p in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, pref_p)
        if api_key:
            if pref_m:
                return (pref_p, pref_m, None)
            m0 = await first_model_id(pref_p)
            if m0:
                return (pref_p, m0, None)
    if "xiaomi" in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, "xiaomi")
        if api_key:
            m0 = await first_model_id("xiaomi")
            if m0:
                return ("xiaomi", m0, None)
    for p in _facade().KNOWN_PROVIDERS:
        api_key, _ = _facade().resolve_api_key(db, user.id, p)
        if not api_key:
            continue
        m0 = await first_model_id(p)
        if m0:
            return (p, m0, None)
    return (None, None, "没有找到已配置 API Key 且可用模型目录的 LLM 供应商")
