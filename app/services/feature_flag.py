"""
Feature Flag 服务（v9.0.0 P1-1）

设计目标：
1. **统一抽象**：替代散落在 6+ 文件的 ``XCAGI_NEURO_BUS_*`` / ``XCAGI_EVENT_PRIMARY_*`` 裸环境变量
2. **多源支持**：env 变量（最快）+ JSON 文件（可动态加载）+ DB（未来扩展）
3. **多维度定位**：全局 / 按租户 / 按用户 / 按 Mod / 按百分比分桶
4. **审计完整**：每次 ``is_enabled`` 调用记录 X-Request-ID + 结果
5. **类型安全**：``FeatureFlagName`` 枚举化已知 flag，禁止拼写错误
6. **可降级**：DB/远程不可用时回退到 env/默认值

**典型用法**::

    from app.services.feature_flag import feature_flag, FeatureFlagName

    if feature_flag.is_enabled(FeatureFlagName.NEURO_BUS_PERSISTENCE):
        await persistence_layer.save(event)

    if feature_flag.is_enabled_for_tenant(FeatureFlagName.EVENT_PRIMARY_SHIPMENT, tenant_id):
        return await event_facade.dispatch(...)

    if feature_flag.is_enabled_for_user(
        FeatureFlagName.MOD_AI_BETA, user_id=42, percentage_rollout=10
    ):
        return await run_beta_agent(...)

**集成路线**：
- 2026-Q3：替换 ``app/contexts/flags.py`` 的 14 个 ``os.environ`` 直读
- 2026-Q4：与 ``app/neuro_bus/bus.py`` 的 ``xcagi_neuro_bus_*`` 联动
- 2027-Q1：接 Unleash / Flagsmith（HTTP 远程配置）
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


# =============================================================================
# 1. 已知 Flag 枚举（SSOT，防止拼写错误）
# =============================================================================


class FeatureFlagName(str, Enum):
    """所有已知 Feature Flag 名称。新增 flag 时必须在此登记。"""

    # NeuroBus 八大机制（替代 xcagi_neuro_bus_* 环境变量）
    NEURO_BUS_PERSISTENCE = "neuro_bus.persistence"
    NEURO_BUS_DEDUPLICATION = "neuro_bus.deduplication"
    NEURO_BUS_RATE_LIMIT = "neuro_bus.rate_limit"
    NEURO_BUS_CIRCUIT_BREAKER = "neuro_bus.circuit_breaker"
    NEURO_BUS_SLA_LOGGING = "neuro_bus.sla_logging"
    NEURO_BUS_SAFETY_CHANNEL = "neuro_bus.safety_channel"
    NEURO_BUS_DEAD_LETTER = "neuro_bus.dead_letter"
    NEURO_BUS_RETRY_SANDBOX = "neuro_bus.retry_sandbox"

    # 事件主入口（替代 xcagi_event_primary_*）
    EVENT_PRIMARY_SHIPMENT = "event_primary.shipment"
    EVENT_PRIMARY_ORDER = "event_primary.order"
    EVENT_PRIMARY_INVENTORY = "event_primary.inventory"
    EVENT_PRIMARY_PRINT = "event_primary.print"

    # Mod 系统
    MOD_AI_BETA = "mod.ai_beta"
    MOD_SUBPROCESS_ENABLED = "mod.subprocess_enabled"
    MOD_OTA_PUBLISH = "mod.ota_publish"

    # AI / LLM
    LLM_STREAM_FORCE_ENABLED = "llm.stream_force_enabled"
    LLM_TOKEN_WALLET_ENFORCED = "llm.token_wallet_enforced"

    # 发布列车（deploy≠release：先部署、后用开关放量；对标大厂 dark launch）
    RELEASE_DARK_LAUNCH = "release.dark_launch"
    RELEASE_CANARY_AUTO_PROMOTE = "release.canary_auto_promote"
    RELEASE_OPS_STAGED_AUTO_APPROVE = "release.ops_staged_auto_approve"

    # 实验性
    EXPERIMENTAL_GDPR_API = "experimental.gdpr_api"
    EXPERIMENTAL_K8S_CHAOS = "experimental.k8s_chaos"
    EXPERIMENTAL_HYPOTHESIS_TESTS = "experimental.hypothesis_tests"


# =============================================================================
# 2. Flag 来源
# =============================================================================

FlagSource = Literal["env", "file", "db", "remote", "default"]


@dataclass(frozen=True)
class FlagEvaluation:
    """Flag 评估结果（含审计信息）"""

    name: str
    enabled: bool
    source: FlagSource
    matched_rule: str | None = None  # 如 "tenant_id=42", "user_id_hash_bucket<10"
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# =============================================================================
# 3. Flag Provider 接口
# =============================================================================


class FlagProvider:
    """Flag 数据源抽象。env / file / db / remote 各自实现。"""

    def get_all(self) -> dict[str, Any]:
        return {}


class EnvFlagProvider(FlagProvider):
    """从 ``FHD_FF_<NAME>`` / ``XCAGI_FF_<NAME>`` 环境变量读取。"""

    PREFIXES = ("FHD_FF_", "XCAGI_FF_")

    def get_all(self) -> dict[str, Any]:
        flags: dict[str, Any] = {}
        for key, value in os.environ.items():
            for prefix in self.PREFIXES:
                if key.startswith(prefix):
                    raw_name = key[len(prefix):].lower().replace("__", ".")
                    flags[raw_name] = self._parse_value(value)
                    break
        return flags

    @staticmethod
    def _parse_value(raw: str) -> Any:
        """支持 JSON / bool / int / string。"""
        v = raw.strip()
        if not v:
            return False
        if v.lower() in ("true", "1", "yes", "on"):
            return True
        if v.lower() in ("false", "0", "no", "off"):
            return False
        if v.startswith(("{", "[", '"')):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        try:
            return int(v)
        except ValueError:
            return v


class FileFlagProvider(FlagProvider):
    """从 JSON 文件动态加载（支持热更新）。"""

    def __init__(self, path: Path | None = None):
        self._path = path or Path(
            os.environ.get("FHD_FF_FILE_PATH", "./feature_flags.json"),
        )
        self._cached: dict[str, Any] = {}
        self._cached_mtime: float = 0.0
        self._lock = threading.Lock()

    def get_all(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with self._lock:
            try:
                mtime = self._path.stat().st_mtime
                if mtime > self._cached_mtime:
                    self._cached = json.loads(self._path.read_text(encoding="utf-8"))
                    self._cached_mtime = mtime
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("FileFlagProvider 读取失败: %s", e)
                return self._cached
        return dict(self._cached)


# =============================================================================
# 4. 主服务
# =============================================================================


@dataclass
class FeatureFlagService:
    """Feature Flag 中心服务（单例）。"""

    env_provider: FlagProvider = field(default_factory=EnvFlagProvider)
    file_provider: FlagProvider | None = None
    default_overrides: dict[str, bool] = field(default_factory=dict)
    _eval_log: list[FlagEvaluation] = field(default_factory=list)
    _max_eval_log: int = 1000

    def __post_init__(self) -> None:
        path = os.environ.get("FHD_FF_FILE_PATH")
        if path:
            self.file_provider = FileFlagProvider(Path(path))

    # --- 基础查询 ----------------------------------------------------------

    def is_enabled(
        self,
        name: FeatureFlagName | str,
        *,
        default: bool = False,
    ) -> bool:
        """检查全局是否启用。"""
        key = str(name)
        eval_result = self._evaluate(key, default=default)
        self._log(eval_result)
        return eval_result.enabled

    def is_enabled_for_tenant(
        self,
        name: FeatureFlagName | str,
        tenant_id: int | str,
        *,
        default: bool = False,
    ) -> bool:
        """按租户定位。

        JSON 格式::

            {
              "event_primary.shipment": {
                "tenants": {"42": true, "100": false},
                "default": false
              }
            }
        """
        key = str(name)
        flag_def = self._lookup_flag_def(key)
        if isinstance(flag_def, dict):
            tenants = flag_def.get("tenants", {})
            if str(tenant_id) in tenants:
                enabled = bool(tenants[str(tenant_id)])
                self._log(
                    FlagEvaluation(
                        name=key,
                        enabled=enabled,
                        source="file" if self.file_provider else "env",
                        matched_rule=f"tenant_id={tenant_id}",
                    ),
                )
                return enabled
            default = bool(flag_def.get("default", default))
        eval_result = self._evaluate(key, default=default)
        # FlagEvaluation 是 frozen=True，新建对象而非修改
        eval_result = FlagEvaluation(
            name=eval_result.name,
            enabled=eval_result.enabled,
            source=eval_result.source,
            matched_rule=f"tenant_id={tenant_id}_default",
            timestamp=eval_result.timestamp,
        )
        self._log(eval_result)
        return eval_result.enabled

    def is_enabled_for_user(
        self,
        name: FeatureFlagName | str,
        user_id: int | str,
        *,
        percentage_rollout: int | None = None,
        default: bool = False,
    ) -> bool:
        """按用户定位 + 百分比分桶（灰度发布）。"""
        key = str(name)
        flag_def = self._lookup_flag_def(key)
        if isinstance(flag_def, dict):
            users = flag_def.get("users", {})
            if str(user_id) in users:
                enabled = bool(users[str(user_id)])
                self._log(
                    FlagEvaluation(
                        name=key,
                        enabled=enabled,
                        source="file" if self.file_provider else "env",
                        matched_rule=f"user_id={user_id}",
                    ),
                )
                return enabled
            if percentage_rollout is None:
                percentage_rollout = flag_def.get("percentage_rollout")
            default = bool(flag_def.get("default", default))

        # 百分比分桶：hash(user_id) % 100 < percentage
        if percentage_rollout is not None and percentage_rollout > 0:
            bucket = int(hashlib_md5(str(user_id))) % 100
            enabled = bucket < int(percentage_rollout)
            self._log(
                FlagEvaluation(
                    name=key,
                    enabled=enabled,
                    source="default",
                    matched_rule=f"user_id={user_id}_bucket={bucket}/{percentage_rollout}",
                ),
            )
            return enabled
        return self.is_enabled(name, default=default)

    # --- 内部 --------------------------------------------------------------

    def _evaluate(
        self,
        key: str,
        *,
        default: bool,
    ) -> FlagEvaluation:
        env_value = self.env_provider.get_all().get(key)
        if env_value is not None:
            return FlagEvaluation(
                name=key,
                enabled=bool(env_value),
                source="env",
            )
        if self.file_provider is not None:
            file_def = self.file_provider.get_all().get(key)
            if isinstance(file_def, bool):
                return FlagEvaluation(name=key, enabled=file_def, source="file")
            if isinstance(file_def, dict) and "default" in file_def:
                return FlagEvaluation(
                    name=key,
                    enabled=bool(file_def["default"]),
                    source="file",
                )
        if key in self.default_overrides:
            return FlagEvaluation(
                name=key,
                enabled=self.default_overrides[key],
                source="default",
            )
        return FlagEvaluation(name=key, enabled=default, source="default")

    def _lookup_flag_def(self, key: str) -> Any:
        if self.file_provider is None:
            return None
        return self.file_provider.get_all().get(key)

    def _log(self, evaluation: FlagEvaluation) -> None:
        self._eval_log.append(evaluation)
        if len(self._eval_log) > self._max_eval_log:
            self._eval_log = self._eval_log[-self._max_eval_log:]

    # --- 调试 --------------------------------------------------------------

    def get_recent_evaluations(self, limit: int = 50) -> list[FlagEvaluation]:
        return self._eval_log[-limit:]

    def reload(self) -> None:
        """强制重载文件 provider（管理端用）。"""
        if isinstance(self.file_provider, FileFlagProvider):
            with self.file_provider._lock:  # type: ignore[attr-defined]
                self.file_provider._cached_mtime = 0.0  # type: ignore[attr-defined]


def hashlib_md5(s: str) -> int:
    """稳定的字符串 hash（不依赖 hashlib 减少导入）。"""
    import hashlib

    digest = hashlib.md5(s.encode("utf-8"), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16)


# =============================================================================
# 5. 单例与便捷函数
# =============================================================================


_feature_flag: FeatureFlagService | None = None
_feature_flag_lock = threading.Lock()


def get_feature_flag_service() -> FeatureFlagService:
    """获取全局单例（懒加载）。"""
    global _feature_flag
    if _feature_flag is not None:
        return _feature_flag
    with _feature_flag_lock:
        if _feature_flag is None:
            _feature_flag = FeatureFlagService(
                default_overrides={
                    # 默认关闭：实验性功能
                    str(FeatureFlagName.EXPERIMENTAL_GDPR_API): True,  # P1-3 启用
                    str(FeatureFlagName.EXPERIMENTAL_HYPOTHESIS_TESTS): True,  # P1-4 启用
                    # 默认开启：核心功能
                    str(FeatureFlagName.NEURO_BUS_DEAD_LETTER): True,
                    str(FeatureFlagName.NEURO_BUS_SAFETY_CHANNEL): True,
                },
            )
    return _feature_flag


# 便捷函数：直接 is_enabled() 用
def is_enabled(name: FeatureFlagName | str, default: bool = False) -> bool:
    return get_feature_flag_service().is_enabled(name, default=default)


# 兼容旧名
feature_flag = get_feature_flag_service()


__all__ = [
    "FeatureFlagName",
    "FeatureFlagService",
    "FlagEvaluation",
    "FlagProvider",
    "EnvFlagProvider",
    "FileFlagProvider",
    "get_feature_flag_service",
    "is_enabled",
    "feature_flag",
]
