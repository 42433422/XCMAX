"""语义意图兜底：规则未命中时用 semantic-router + FastEmbed 做向量召回。

设计边界：
- 规则引擎始终优先；本层只在规则没有任何工具命中时执行。
- 只输出候选 tool_key / intent，不授予工具权限，也不绕过否定守卫。
- 不依赖 torch：FastEmbed 使用 ONNX Runtime；模型缺失或依赖不可用时静默降级为规则。
- 路由语料直接来自 ``resources/config/intent_config.yaml`` 的 keywords，
  避免维护第二份意图真相源。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
_DEFAULT_THRESHOLD = 0.55
_DEFAULT_OVERRIDE_THRESHOLD = 0.74
_DEFAULT_OVERRIDE_MAX_PRIORITY = 13
_ENV_ENABLED = "FHD_INTENT_SEMANTIC_ENABLED"
_ENV_THRESHOLD = "FHD_INTENT_SEMANTIC_THRESHOLD"
_ENV_OVERRIDE_THRESHOLD = "FHD_INTENT_SEMANTIC_OVERRIDE_THRESHOLD"
_ENV_OVERRIDE_MAX_PRIORITY = "FHD_INTENT_SEMANTIC_OVERRIDE_MAX_PRIORITY"
_ENV_MODEL = "FHD_INTENT_SEMANTIC_MODEL"
_ENV_MODEL_DIR = "FHD_INTENT_SEMANTIC_MODEL_DIR"


@dataclass(frozen=True)
class SemanticIntent:
    """语义层命中结果。``intent_id`` 与规则层的 primary_intent 对齐。"""

    intent_id: str
    tool_key: str
    score: float


@dataclass(frozen=True)
class _RouteSpec:
    name: str
    utterances: list[str]


def _env_flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def semantic_enabled() -> bool:
    return _env_flag(_ENV_ENABLED, True)


def semantic_threshold() -> float:
    raw = (os.environ.get(_ENV_THRESHOLD, "") or "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        return min(0.99, max(0.0, float(raw)))
    except ValueError:
        return _DEFAULT_THRESHOLD


def semantic_override_threshold() -> float:
    """覆盖低置信规则匹配所需的最低相似度。"""
    raw = (os.environ.get(_ENV_OVERRIDE_THRESHOLD, "") or "").strip()
    if not raw:
        return _DEFAULT_OVERRIDE_THRESHOLD
    try:
        return min(0.99, max(0.0, float(raw)))
    except ValueError:
        return _DEFAULT_OVERRIDE_THRESHOLD


def semantic_override_max_priority() -> int:
    """规则优先级低于该值时才允许被语义结果覆盖。"""
    raw = (os.environ.get(_ENV_OVERRIDE_MAX_PRIORITY, "") or "").strip()
    if not raw:
        return _DEFAULT_OVERRIDE_MAX_PRIORITY
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_OVERRIDE_MAX_PRIORITY


def semantic_model_name() -> str:
    return (os.environ.get(_ENV_MODEL, "") or "").strip() or _DEFAULT_MODEL


def _resolve_model_dir() -> str:
    """优先环境变量，其次随包资源，最后交给 FastEmbed 默认缓存。"""
    explicit = (os.environ.get(_ENV_MODEL_DIR, "") or "").strip()
    if explicit:
        return explicit

    candidates: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "models" / "fastembed")
    candidates.append(Path(__file__).resolve().parents[3] / "assets" / "models" / "fastembed")
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    return ""


_lock = threading.Lock()
_router: Any | None = None
_router_error = ""
_intent_by_tool: dict[str, str] = {}
_route_count = 0

_CORPUS_RELATIVE_PATH = "resources/config/intent_semantic_utterances.yaml"


def _load_corpus() -> dict[str, list[str]]:
    """读取构建期生成的语料；缺失不影响规则，只降低召回。"""
    try:
        root = Path(__file__).resolve().parents[3]
        payload = yaml.safe_load((root / _CORPUS_RELATIVE_PATH).read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get("utterances", {}), dict):
            return {}
        corpus: dict[str, list[str]] = {}
        for tool_key, items in (payload.get("utterances") or {}).items():
            if not isinstance(items, list):
                continue
            texts = [str(item).strip() for item in items or [] if str(item).strip()]
            if texts:
                corpus[str(tool_key)] = texts
        return corpus
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.warning("intent semantic corpus unavailable: %s", exc)
        return {}


def _build_routes() -> tuple[list[_RouteSpec], dict[str, str]]:
    """从意图配置关键词与构建期语料构建路由；同名 tool_key 合并。"""
    from resources.config.intent_config import get_intent_config

    config = get_intent_config()
    buckets: dict[str, dict[str, Any]] = {}
    for intent in config.get("tool_intents") or []:
        tool_key = str(intent.get("tool_key") or "").strip()
        if not tool_key:
            continue
        bucket = buckets.setdefault(
            tool_key,
            {"intent_id": str(intent.get("id") or tool_key).strip(), "utterances": []},
        )
        for keyword in intent.get("keywords") or []:
            text = str(keyword or "").strip()
            if text and text not in bucket["utterances"]:
                bucket["utterances"].append(text)

    for tool_key, texts in _load_corpus().items():
        corpus_bucket = buckets.get(tool_key)
        if corpus_bucket is None:
            continue
        for text in texts:
            if text not in corpus_bucket["utterances"]:
                corpus_bucket["utterances"].append(text)

    routes: list[_RouteSpec] = []
    intent_by_tool: dict[str, str] = {}
    for tool_key, bucket in buckets.items():
        utterances = bucket["utterances"]
        if len(utterances) < 2:
            continue
        routes.append(_RouteSpec(name=tool_key, utterances=utterances))
        intent_by_tool[tool_key] = str(bucket["intent_id"])
    return routes, intent_by_tool


def _build_router() -> tuple[Any, dict[str, str]]:
    # The optional backend is loaded only at this plugin boundary; callers and
    # corpus construction consume our typed specs without requiring the extra.
    backend = import_module("semantic_router")
    Route, IndexedRouter = backend.Route, backend.IndexedRouter
    FastEmbedEncoder = import_module("semantic_router.encoders").FastEmbedEncoder

    route_specs, intent_by_tool = _build_routes()
    routes = [Route(name=spec.name, utterances=spec.utterances) for spec in route_specs]
    if not routes:
        raise RuntimeError("intent config produced no semantic routes")

    model_kwargs: dict[str, Any] = {"name": semantic_model_name()}
    cache_dir = _resolve_model_dir()
    if cache_dir:
        # 随包模型已就绪时禁止联网探测，保证离线可用。
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        model_kwargs["cache_dir"] = cache_dir
    encoder = FastEmbedEncoder(**model_kwargs)

    router = IndexedRouter(
        encoder=encoder,
        routes=routes,
        top_k=4,
        confidence_threshold=semantic_threshold(),
    )
    return router, intent_by_tool


def get_semantic_router() -> Any | None:
    """懒加载单例；任何失败都只记录一次并返回 None。"""
    global _router, _router_error, _intent_by_tool, _route_count

    if _router is not None:
        return _router
    if _router_error:
        return None
    if not semantic_enabled():
        return None

    with _lock:
        if _router is not None:
            return _router
        if _router_error:
            return None
        try:
            router, intent_by_tool = _build_router()
            _router = router
            _route_count = len(router.routes)
            _intent_by_tool = intent_by_tool
            logger.info(
                "intent semantic router ready: model=%s routes=%s threshold=%s",
                semantic_model_name(),
                _route_count,
                semantic_threshold(),
            )
        except BOUNDARY_ERRORS as exc:  # Third-party model initialization is a plugin boundary.
            _router_error = f"{type(exc).__name__}: {exc}"
            logger.warning("intent semantic router unavailable: %s", _router_error)
            _router = None
    return _router


def route_intent(text: str) -> SemanticIntent | None:
    """返回语义命中的意图；未启用、不可用或低于阈值时返回 None。"""
    if not text or not semantic_enabled():
        return None
    router = get_semantic_router()
    if router is None:
        return None

    try:
        choice = router(text, limit=1)
    except BOUNDARY_ERRORS as exc:  # Isolate third-party inference, not rule/permission execution.
        logger.warning("intent semantic route failed: %s", exc)
        return None

    if isinstance(choice, list):
        choice = choice[0] if choice else None
    if choice is None:
        return None

    score = float(getattr(choice, "confidence", 0.0) or 0.0)
    if score < semantic_threshold():
        return None

    tool_key = str(getattr(choice, "name", "") or "").strip()
    if not tool_key:
        return None
    return SemanticIntent(
        intent_id=_intent_by_tool.get(tool_key, tool_key),
        tool_key=tool_key,
        score=round(score, 4),
    )


def semantic_router_status() -> dict[str, Any]:
    """诊断快照；不触发模型加载。"""
    return {
        "enabled": semantic_enabled(),
        "loaded": _router is not None,
        "error": _router_error or None,
        "routes": _route_count,
        "model": semantic_model_name(),
        "threshold": semantic_threshold(),
        "override_threshold": semantic_override_threshold(),
        "override_max_priority": semantic_override_max_priority(),
    }


def reload_semantic_router() -> None:
    """配置或模型变更后重建索引。"""
    global _router, _router_error, _intent_by_tool, _route_count
    with _lock:
        _router = None
        _router_error = ""
        _intent_by_tool = {}
        _route_count = 0
