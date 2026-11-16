"""基于 semantic-router + fastembed(ONNX) 的语义意图识别。

设计要点：

- 意图用示例句定义（见 ``route_catalog``），靠向量相似度匹配，不写正则、不训练。
- 模型走本地 ONNX（``BAAI/bge-small-zh-v1.5``），不依赖 torch；模型缺失或加载失败时
  返回空结果，调用方继续使用既有规则，离线构建不会因模型未打包而不可用。
- 首次识别才加载模型（懒加载），避免拖慢应用启动。

环境变量：
  ``XCAGI_INTENT_ENGINE``        off 时完全停用语义识别，只用规则
  ``XCAGI_INTENT_MODEL``         覆盖默认模型（默认 BAAI/bge-small-zh-v1.5）
  ``XCAGI_INTENT_MODEL_CACHE``   ONNX 模型缓存目录（打包时预置到该目录即可离线）
  ``XCAGI_INTENT_THRESHOLD``     置信度阈值（默认 0.55）
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .route_catalog import INTENT_DESCRIPTIONS, INTENT_UTTERANCES

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_THRESHOLD = 0.55

_router: Any = None
_router_load_failed = False
_lock = threading.Lock()


@dataclass(frozen=True)
class IntentMatch:
    """一条语义意图命中。``source`` 便于日志区分语义/规则来源。"""

    intent: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    source: str = "semantic"


def engine_enabled() -> bool:
    raw = (os.environ.get("XCAGI_INTENT_ENGINE", "") or "").strip().lower()
    if raw in {"on", "1", "true", "enabled"}:
        return True
    if raw in {"off", "0", "false", "disabled"}:
        return False
    # 测试环境默认关闭：模型需要下载且体积较大，语义层用桩测试；
    # 需要真实跑模型时显式设置 XCAGI_INTENT_ENGINE=on。
    return not bool(os.environ.get("PYTEST_CURRENT_TEST"))


def threshold() -> float:
    raw = (os.environ.get("XCAGI_INTENT_THRESHOLD", "") or "").strip()
    try:
        return min(max(float(raw), 0.0), 1.0)
    except ValueError:
        return DEFAULT_THRESHOLD


def _bundled_model_dir() -> Any:
    """打包产物里的只读模型目录（PyInstaller ``_MEIPASS/models/fastembed``）。"""
    import sys
    from pathlib import Path

    if not getattr(sys, "frozen", False):
        return None
    base = Path(str(getattr(sys, "_MEIPASS", ""))) / "models" / "fastembed"
    return base if base.is_dir() else None


def _model_cache_dir() -> str | None:
    """返回可写的模型缓存目录；打包模型只读，首次使用时复制出来。"""
    explicit = (os.environ.get("XCAGI_INTENT_MODEL_CACHE", "") or "").strip()
    if explicit:
        return explicit
    try:
        from pathlib import Path

        from app.utils.path_io.path_utils import get_app_data_dir

        target = Path(str(get_app_data_dir())) / "models" / "fastembed"
        bundled = _bundled_model_dir()
        if bundled is not None and not (target / "models--Qdrant--bge-small-zh-v1.5").exists():
            import shutil

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(bundled, target, dirs_exist_ok=True)
            except OSError as exc:
                # 复制失败时继续用只读目录尝试加载，失败再自然回退规则。
                logger.warning("意图模型缓存复制失败：%s", type(exc).__name__)
                return str(bundled)
        return str(target)
    except RECOVERABLE_ERRORS:
        return None


def _build_router() -> Any:
    """构造 IndexedRouter；任何依赖缺失都返回 None（交由规则兜底）。"""
    from semantic_router import Route
    from semantic_router.encoders import FastEmbedEncoder
    from semantic_router.routers import IndexedRouter

    model = (os.environ.get("XCAGI_INTENT_MODEL", "") or "").strip() or DEFAULT_MODEL
    encoder = FastEmbedEncoder(
        name=model,
        cache_dir=_model_cache_dir(),
        # 桌面端不必抢占全部核心，留出推理余量。
        threads=max(1, min(2, os.cpu_count() or 2)),
    )
    routes = [
        Route(
            name=name,
            description=INTENT_DESCRIPTIONS.get(name, ""),
            utterances=list(utterances),
        )
        for name, utterances in INTENT_UTTERANCES.items()
        if utterances
    ]
    return IndexedRouter(encoder=encoder, routes=routes)


def _load_router() -> Any:
    global _router, _router_load_failed
    if _router is not None or _router_load_failed:
        return _router
    with _lock:
        if _router is not None or _router_load_failed:
            return _router
        try:
            _router = _build_router()
            logger.info("语义意图路由器已加载（%s）", DEFAULT_MODEL)
        except RECOVERABLE_ERRORS as exc:
            # 依赖缺失或模型不可用时只降级，不影响主流程。
            _router_load_failed = True
            logger.info("语义意图路由器不可用，回退规则判定：%s", type(exc).__name__)
        return _router


def is_available() -> bool:
    return _load_router() is not None


def classify_intents(text: str, *, limit: int = 3) -> list[IntentMatch]:
    """返回按相似度排序的意图命中；模型不可用时返回空列表。"""
    query = str(text or "").strip()
    if not query or not engine_enabled():
        return []
    router = _load_router()
    if router is None:
        return []
    try:
        picked = router(query, limit=None, threshold=0.0)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("语义意图识别失败，回退规则判定：%s", exc)
        return []
    choices = picked if isinstance(picked, list) else [picked]
    matches: list[IntentMatch] = []
    for choice in choices:
        name = str(getattr(choice, "name", "") or "")
        if not name:
            continue
        confidence = round(float(getattr(choice, "confidence", 0.0) or 0.0), 4)
        matches.append(IntentMatch(intent=name, confidence=confidence))
    matches.sort(key=lambda item: item.confidence, reverse=True)
    return matches[: max(1, int(limit))]


def best_intent(text: str, *, min_confidence: float | None = None) -> IntentMatch | None:
    """返回置信度达标的最佳意图；不达标视为无法判定。"""
    bar = threshold() if min_confidence is None else min_confidence
    for match in classify_intents(text, limit=3):
        if match.confidence >= bar:
            return match
    return None


def reset_for_tests() -> None:
    """测试用：清空单例与失败标记。"""
    global _router, _router_load_failed
    with _lock:
        _router = None
        _router_load_failed = False


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_THRESHOLD",
    "IntentMatch",
    "best_intent",
    "classify_intents",
    "engine_enabled",
    "is_available",
    "reset_for_tests",
    "threshold",
]
