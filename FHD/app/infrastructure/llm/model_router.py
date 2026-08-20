"""ModelRouter — 按任务复杂度在小/大 LLM 之间路由。

与 ``app.neuro_bus.routing.cognitive_router.CognitiveRouter`` 正交：
- CognitiveRouter 决定"走哪一级处理器"（Reflex / Subconscious / Conscious）
- ModelRouter 决定"LLM 调用用小模型还是大模型"

仅在 Conscious 级 LLM 调用前置生效；不影响 Reflex / Subconscious 路径。

路由规则（可配置，``config/model_routing.json`` + 环境变量覆盖）：
    1. profile="reasoning"  → 强制 large
    2. profile="fast"       → 强制 small
    3. 复杂意图（intent 命中 large_intent_keywords 或消息命中关键词） → large
    4. 消息长度 > 阈值       → large
    5. 工具数 > 阈值         → large
    6. 对话历史 > 阈值       → large
    7. 默认                  → small（成本优先）

环境变量（优先级高于配置文件）：
    - ``FHD_MODEL_ROUTING_ENABLED``：总开关（默认 ``false``，行为与现状一致）
    - ``FHD_MODEL_SMALL``：小模型名称（默认 ``deepseek-chat``）
    - ``FHD_MODEL_LARGE``：大模型名称（默认 ``deepseek-reasoner``）

向后兼容：``FHD_MODEL_ROUTING_ENABLED`` 未开启时，``route`` 返回默认 tier，
调用方应优先检查 ``ModelRouter.enabled`` 决定是否消费 decision。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

ModelTier = Literal["small", "large"]

_DEFAULT_CONFIG_PATH = "config/model_routing.json"
_DEFAULT_SMALL_MODEL = "deepseek-chat"
_DEFAULT_LARGE_MODEL = "deepseek-reasoner"
_DEFAULT_LARGE_INTENT_KEYWORDS: tuple[str, ...] = (
    "分析",
    "规划",
    "报表",
    "对比",
    "总结",
    "预测",
    "workflow",
    "multi_step",
)
_DEFAULT_LARGE_MESSAGE_LENGTH = 2000
_DEFAULT_LARGE_TOOL_COUNT = 3
_DEFAULT_LARGE_HISTORY_TURNS = 10

# 简单意图白名单（CRUD 类）— 仅用于文档与测试断言；route() 实际判定基于 large_intent_keywords
_SIMPLE_INTENT_HINTS: frozenset[str] = frozenset(
    {
        "shipment_generate",
        "customers",
        "products",
        "product_query",
        "customers_query",
        "price_list",
        "label_print",
        "inventory_alert",
        "shipment",
        "greeting",
        "help",
        "goodbye",
    }
)


@dataclass
class RoutingRequest:
    """路由请求。

    Attributes:
        message: 用户消息文本（用于长度判定与关键词扫描）。
        intent: 已识别的意图标签（可为 ``None``；命中 large_intent_keywords 时升级 large）。
        tool_count: 本次请求预期的工具调用数量（用于复杂度判定）。
        conversation_history_len: 当前会话历史轮次数（用于上下文长度判定）。
        profile: 强制画像；``"reasoning"`` 强制 large，``"fast"`` 强制 small，``None`` 走规则。
    """

    message: str
    intent: str | None = None
    tool_count: int = 0
    conversation_history_len: int = 0
    profile: str | None = None

    def __post_init__(self) -> None:
        # 防御性规范化，避免外部传入非法类型时炸掉路由判定
        self.message = str(self.message or "")
        if self.intent is not None:
            self.intent = str(self.intent).strip() or None
        if self.profile is not None:
            self.profile = str(self.profile).strip().lower() or None
        try:
            self.tool_count = int(self.tool_count)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self.tool_count = 0
        try:
            self.conversation_history_len = int(self.conversation_history_len)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self.conversation_history_len = 0


@dataclass
class RoutingDecision:
    """路由决策。

    Attributes:
        model_tier: ``"small"`` 或 ``"large"``。
        model_name: 实际模型名（来自 ``FHD_MODEL_SMALL`` / ``FHD_MODEL_LARGE``）。
        reason: 决策原因（人类可读，用于审计日志）。
    """

    model_tier: ModelTier
    model_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_tier": self.model_tier,
            "model_name": self.model_name,
            "reason": self.reason,
        }


@dataclass
class _RoutingConfig:
    """路由配置（从 JSON + 环境变量加载）。"""

    default_tier: ModelTier = "small"
    small_model: str = _DEFAULT_SMALL_MODEL
    large_model: str = _DEFAULT_LARGE_MODEL
    large_intent_keywords: tuple[str, ...] = _DEFAULT_LARGE_INTENT_KEYWORDS
    large_message_length: int = _DEFAULT_LARGE_MESSAGE_LENGTH
    large_tool_count: int = _DEFAULT_LARGE_TOOL_COUNT
    large_history_turns: int = _DEFAULT_LARGE_HISTORY_TURNS


def _coerce_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        v = int(value)  # type: ignore[arg-type]
        return max(minimum, v)
    except (TypeError, ValueError):
        return default


class ModelRouter:
    """模型路由器。

    用法::

        router = ModelRouter()
        if router.enabled:
            decision = router.route(RoutingRequest(message="...", intent="...", profile="reasoning"))
            # decision.model_tier ∈ {"small", "large"}
            # decision.model_name 实际模型名

    单例友好：通过 :func:`get_model_router` 获取进程级单例；测试可独立 ``ModelRouter()``
    实例化以隔离配置。
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._config = self._load_config()
        self._enabled = _coerce_bool(os.environ.get("FHD_MODEL_ROUTING_ENABLED"), False)

    # ---------------- 配置加载 ----------------

    def _load_config(self) -> _RoutingConfig:
        cfg = _RoutingConfig()

        # 1) 从 JSON 加载（best-effort）
        try:
            data = self._read_json_config()
            if isinstance(data, dict):
                cfg.default_tier = self._validate_tier(data.get("default_tier"), cfg.default_tier)
                if isinstance(data.get("small_model"), str) and data["small_model"]:
                    cfg.small_model = data["small_model"]
                if isinstance(data.get("large_model"), str) and data["large_model"]:
                    cfg.large_model = data["large_model"]
                rules = data.get("rules") or {}
                if isinstance(rules, dict):
                    cfg.large_intent_keywords = self._coerce_keywords(
                        rules.get("large_intent_keywords"), cfg.large_intent_keywords
                    )
                    cfg.large_message_length = _coerce_int(
                        rules.get("large_message_length"),
                        cfg.large_message_length,
                        minimum=1,
                    )
                    cfg.large_tool_count = _coerce_int(
                        rules.get("large_tool_count"), cfg.large_tool_count, minimum=1
                    )
                    cfg.large_history_turns = _coerce_int(
                        rules.get("large_history_turns"),
                        cfg.large_history_turns,
                        minimum=1,
                    )
        except RECOVERABLE_ERRORS as err:
            logger.debug("model_routing.json 加载失败，使用默认配置: %s", err)

        # 2) 环境变量覆盖（优先级最高）
        env_small = (os.environ.get("FHD_MODEL_SMALL") or "").strip()
        if env_small:
            cfg.small_model = env_small
        env_large = (os.environ.get("FHD_MODEL_LARGE") or "").strip()
        if env_large:
            cfg.large_model = env_large
        return cfg

    def _read_json_config(self) -> dict[str, Any] | None:
        path = Path(self._config_path)
        if not path.is_absolute():
            repo_root = self._resolve_repo_root()
            if repo_root is not None:
                path = repo_root / path
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return cast("dict[str, Any] | None", json.load(f))

    @staticmethod
    def _resolve_repo_root() -> Path | None:
        # app/infrastructure/llm/model_router.py → 向上查找包含 app/ 与 config/ 的目录
        here = Path(__file__).resolve()
        for parent in [here.parent, *here.parents]:
            if (parent / "app" / "infrastructure" / "llm").is_dir() and (
                parent / "config"
            ).is_dir():
                return parent
        return None

    @staticmethod
    def _validate_tier(value: Any, default: ModelTier) -> ModelTier:
        v = str(value or "").strip().lower()
        return cast("ModelTier", v) if v in {"small", "large"} else default

    @staticmethod
    def _coerce_keywords(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
        if not isinstance(value, list):
            return default
        out = tuple(str(x).strip() for x in value if str(x).strip())
        return out or default

    # ---------------- 公共 API ----------------

    @property
    def enabled(self) -> bool:
        """路由是否启用。

        ``False`` 时调用方应走原逻辑；``route`` 自身仍会返回默认 tier 的 decision
        以保证不抛错。
        """
        return self._enabled

    @property
    def config(self) -> _RoutingConfig:
        """暴露当前配置（仅供测试与诊断使用）。"""
        return self._config

    @staticmethod
    def is_simple_intent(intent: str | None) -> bool:
        """工具方法：判断 intent 是否落在简单 CRUD 白名单。"""
        if not intent:
            return False
        return str(intent).strip().lower() in _SIMPLE_INTENT_HINTS

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数。

        - 中文字符按 1.5 字/token（即每字 ≈ 0.67 token）
        - 英文/ASCII 按 4 字符/token

        Args:
            text: 待估算文本。

        Returns:
            估算的 token 数（``≥0``）。
        """
        if not text:
            return 0
        s = str(text)
        cjk = sum(1 for ch in s if self._is_cjk(ch))
        non_cjk = len(s) - cjk
        # 中文字符：1.5 字/token → token = cjk / 1.5
        # 非 CJK：4 字符/token → token = non_cjk / 4
        return max(0, int(round(cjk / 1.5 + non_cjk / 4)))

    @staticmethod
    def _is_cjk(ch: str) -> bool:
        code = ord(ch)
        # CJK Unified Ideographs 主区块 + 扩展 A + 兼容表意 + 扩展 B（粗判够用）
        return (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xF900 <= code <= 0xFAFF
            or 0x20000 <= code <= 0x2A6DF
        )

    def route(self, request: RoutingRequest) -> RoutingDecision:
        """根据请求决定使用 small / large 模型。

        规则优先级（高 → 低）：
            1. ``profile="reasoning"`` → 强制 large
            2. ``profile="fast"`` → 强制 small
            3. 复杂意图（intent 或 message 命中 ``large_intent_keywords``） → large
            4. 消息长度 > ``large_message_length`` → large
            5. 工具数 > ``large_tool_count`` → large
            6. 对话历史 > ``large_history_turns`` → large
            7. 默认 → small（成本优先）

        Args:
            request: 路由请求。

        Returns:
            :class:`RoutingDecision`
        """
        cfg = self._config

        # 未启用时返回默认 tier 的 decision（安全回退）
        if not self._enabled:
            return RoutingDecision(
                model_tier=cfg.default_tier,
                model_name=(cfg.small_model if cfg.default_tier == "small" else cfg.large_model),
                reason="routing disabled, fallback to default tier",
            )

        # 1) profile 强制
        if request.profile == "reasoning":
            return RoutingDecision(
                model_tier="large",
                model_name=cfg.large_model,
                reason="profile=reasoning forces large",
            )
        if request.profile == "fast":
            return RoutingDecision(
                model_tier="small",
                model_name=cfg.small_model,
                reason="profile=fast forces small",
            )

        # 2) 复杂意图 / 关键词
        large_kw = self._match_large_keyword(request.intent, request.message)
        if large_kw is not None:
            return RoutingDecision(
                model_tier="large",
                model_name=cfg.large_model,
                reason=f"intent/message matches large keyword {large_kw!r}",
            )

        # 3) 长消息
        msg_len = len(request.message)
        if msg_len > cfg.large_message_length:
            return RoutingDecision(
                model_tier="large",
                model_name=cfg.large_model,
                reason=f"message length {msg_len} > {cfg.large_message_length}",
            )

        # 4) 多工具
        if request.tool_count > cfg.large_tool_count:
            return RoutingDecision(
                model_tier="large",
                model_name=cfg.large_model,
                reason=f"tool_count {request.tool_count} > {cfg.large_tool_count}",
            )

        # 5) 长历史
        if request.conversation_history_len > cfg.large_history_turns:
            return RoutingDecision(
                model_tier="large",
                model_name=cfg.large_model,
                reason=(
                    f"history_len {request.conversation_history_len} > {cfg.large_history_turns}"
                ),
            )

        # 6) 默认 → small（成本优先）
        return RoutingDecision(
            model_tier="small",
            model_name=cfg.small_model,
            reason="default to small (cost optimized)",
        )

    def _match_large_keyword(self, intent: str | None, message: str) -> str | None:
        keywords = self._config.large_intent_keywords
        if intent:
            intent_l = intent.lower()
            for kw in keywords:
                if kw and kw.lower() in intent_l:
                    return kw
        msg = str(message or "")
        for kw in keywords:
            if kw and kw in msg:
                return kw
        return None


# ---------------- 单例 ----------------

_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局 :class:`ModelRouter` 单例（进程内 lazy 初始化）。"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_model_router() -> None:
    """重置单例（测试用）。"""
    global _router
    _router = None


__all__ = [
    "ModelRouter",
    "RoutingDecision",
    "RoutingRequest",
    "get_model_router",
    "reset_model_router",
]
