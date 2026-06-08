"""vibe-coding ↔ MODstore 共享适配层。

设计目标:
- 让 MODstore 现有的 LLM Key 解析(``llm_chat_proxy.chat_dispatch`` /
  ``services.llm.chat_dispatch_via_session``)成为 vibe-coding 的唯一上游,
  避免双套配置。
- 让 ``VibeCoder`` / ``ProjectVibeCoder`` 单例化、按用户隔离 ``store_dir``,
  既复用索引/补丁台账缓存,又满足租户隔离。
- 让所有调用方在 vibe-coding 缺失时收到清晰的错误,不要在导入期就把整个
  MODstore 拉崩。

进程内调用方:
- :mod:`modstore_server.mod_scaffold_runner` / :mod:`mod_employee_impl_scaffold`
  自愈 LLM 初稿。
- :mod:`modstore_server.integrations.vibe_action_handlers` 给 employee_executor
  提供 ``vibe_edit`` / ``vibe_heal`` / ``vibe_code`` 三个 action handler。
- :mod:`modstore_server.integrations.vibe_eskill_adapter` 给 ESkill 加
  ``kind: vibe_code | vibe_workflow`` 委派。
- :mod:`modstore_server.workflow_engine` 画布的 ``vibe_skill`` /
  ``vibe_workflow`` 节点。
- :mod:`modstore_server.script_agent.agent_loop` 用 vibe 的 heal 闭环
  替换原 plan/write/check/sandbox/repair。
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from modstore_server.runtime_async import run_coro_sync

if TYPE_CHECKING:  # pragma: no cover - 仅给类型检查;运行时 lazy import
    from vibe_coding import LLMClient, VibeCoder
    from vibe_coding.agent.coder import ProjectVibeCoder

logger = logging.getLogger(__name__)


class VibeIntegrationError(RuntimeError):
    """vibe-coding 未安装,或安装版本与本适配层不兼容。"""


class VibePathError(VibeIntegrationError):
    """租户路径越界:目标 root 不在当前用户的工作区下。"""


# ---------------------------------------------------------------------------
# import lazy helpers
# ---------------------------------------------------------------------------


def _import_vibe_coding() -> Any:
    """惰性导入 :mod:`vibe_coding`,首次失败抛 :class:`VibeIntegrationError`。"""
    try:
        import vibe_coding  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise VibeIntegrationError(
            "未安装 vibe-coding 包。请在部署/开发机执行 "
            "`pip install -e ../vibe-coding[web]`,或在 MODstore_deploy 安装时带 "
            "`[vibe]` extras。"
        ) from exc
    return vibe_coding


def _import_facade() -> tuple[type, type]:
    """返回 ``(VibeCoder, ProjectVibeCoder)`` 类。"""
    vc = _import_vibe_coding()
    from vibe_coding.agent.coder import ProjectVibeCoder  # type: ignore[import-not-found]

    return vc.VibeCoder, ProjectVibeCoder


def vibe_available() -> bool:
    """方便上游做 try/except 之外的 capability 探测。"""
    try:
        _import_vibe_coding()
    except VibeIntegrationError:
        return False
    return True


# ---------------------------------------------------------------------------
# LLMClient adapter:把 chat_dispatch 包成 vibe-coding 期望的同步契约
# ---------------------------------------------------------------------------


class ChatDispatchLLMClient:
    """把 :func:`chat_dispatch_via_session` / :func:`chat_dispatch` 适配成
    vibe-coding 的 :class:`LLMClient` Protocol(同步 ``chat`` 返回 str)。

    构造方式:
    - 推荐:``ChatDispatchLLMClient.from_user(session, user_id, provider, model)``
      用 BYOK + 平台 Key 解析,自动消耗 quota。
    - 直连:``ChatDispatchLLMClient(provider, api_key=..., model=...)``
      跳过 session(给纯 admin / CI 路径用)。
    """

    def __init__(
        self,
        provider: str,
        *,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        default_max_tokens: int = 4096,
        session: Any = None,
        user_id: int = 0,
        use_session_dispatch: bool = False,
    ) -> None:
        self.provider = (provider or "").strip()
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.base_url = base_url
        self.default_max_tokens = int(default_max_tokens)
        self._session = session
        self._user_id = int(user_id or 0)
        self._use_session_dispatch = bool(use_session_dispatch)

    @classmethod
    def from_user(
        cls,
        session: Any,
        user_id: int,
        provider: str,
        model: str,
        *,
        default_max_tokens: int = 8192,
    ) -> "ChatDispatchLLMClient":
        """走 ``llm_key_resolver`` 解析 BYOK / 平台 Key,使用 session 路径调用。"""
        from modstore_server.llm_key_resolver import (
            OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
            resolve_api_key,
            resolve_base_url,
        )

        api_key, _ = resolve_api_key(session, user_id, provider)
        base_url = (
            resolve_base_url(session, user_id, provider)
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
        return cls(
            provider,
            api_key=api_key or "",
            model=model,
            base_url=base_url,
            default_max_tokens=default_max_tokens,
            session=session,
            user_id=user_id,
            use_session_dispatch=True,
        )

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
        """同步阻塞:vibe-coding 的 LLMClient 协议要求。

        - ``json_mode`` 在 :func:`chat_dispatch` 上没有原生开关,我们通过 system
          提示要求模型只输出 JSON,并在拿到响应后做温和的兜底(去掉 markdown 围栏)。
        - 异常路径返回最详细的错误字符串,vibe-coding 上层会把它包装成 LLMError。
        """
        from vibe_coding import LLMError  # type: ignore[import-not-found]

        messages = []
        sys_msg = (system or "").strip()
        if json_mode:
            sys_msg = (
                sys_msg + "\n\n" if sys_msg else ""
            ) + "你必须只输出一个合法 JSON 对象。不要 markdown,不要解释,不要 ``` 包裹。"
        if sys_msg:
            messages.append({"role": "system", "content": sys_msg})
        messages.append({"role": "user", "content": user or ""})

        if self._use_session_dispatch and self._session is not None:
            from modstore_server.services.llm import chat_dispatch_via_session

            result = run_coro_sync(
                chat_dispatch_via_session(
                    self._session,
                    self._user_id,
                    self.provider,
                    self.model,
                    messages,
                    max_tokens=self.default_max_tokens,
                )
            )
        else:
            from modstore_server.llm_chat_proxy import chat_dispatch

            if not self.api_key:
                raise LLMError(
                    f"vibe-coding LLMClient: 未为 provider={self.provider!r} 配置 api_key"
                )
            result = run_coro_sync(
                chat_dispatch(
                    self.provider,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self.model,
                    messages=messages,
                    max_tokens=self.default_max_tokens,
                )
            )
        if not result.get("ok"):
            raise LLMError(
                f"chat_dispatch failed provider={self.provider} model={self.model}: "
                f"{result.get('error') or result.get('status') or 'unknown error'}"
            )
        content = str(result.get("content") or "").strip()
        if not content:
            raise LLMError("chat_dispatch returned empty content")
        if json_mode:
            content = _strip_markdown_fences(content)
        return content


def _strip_markdown_fences(text: str) -> str:
    """如果 LLM 顽皮地回了 ```json\n{...}\n```,剥掉外壳。"""
    s = text.strip()
    if not s.startswith("```"):
        return s
    m = re.match(r"```(?:json|JSON)?\s*([\s\S]*?)```\s*$", s)
    if m:
        return m.group(1).strip()
    return s


# ---------------------------------------------------------------------------
# VibeCoder / ProjectVibeCoder 单例缓存
# ---------------------------------------------------------------------------


_LOCK = threading.Lock()
_CODER_CACHE: Dict[Tuple[int, str], Any] = {}


def _vibe_store_dir(user_id: int) -> Path:
    """租户级 store_dir:用 ``MODSTORE_DATA_DIR``(若有)拼出 vibe 子目录。"""
    base = (
        os.environ.get("VIBE_CODING_STORE_DIR")
        or os.environ.get("MODSTORE_DATA_DIR")
        or str(Path.cwd() / "var" / "vibe_coding")
    )
    p = Path(base) / "users" / str(user_id or 0)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_vibe_coder(
    *,
    session: Any = None,
    user_id: int = 0,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Any:
    """获取 :class:`VibeCoder` 单例(按 user_id + provider 缓存)。

    必填:provider/model(否则抛错)。调用方通常用
    ``resolve_llm_provider_model_auto`` 先把 provider/model 取出来。
    """
    if not provider or not model:
        raise VibeIntegrationError(
            "get_vibe_coder 需要 provider/model;请用 resolve_llm_provider_model 先解析"
        )
    VibeCoder, _ = _import_facade()
    key = (int(user_id or 0), f"{provider}::{model}")
    with _LOCK:
        coder = _CODER_CACHE.get(key)
        if coder is not None:
            return coder
        llm = ChatDispatchLLMClient.from_user(session, int(user_id or 0), provider, model)
        coder = VibeCoder(llm=llm, store_dir=_vibe_store_dir(user_id))
        _CODER_CACHE[key] = coder
        return coder


def get_project_vibe_coder(
    root: str | Path,
    *,
    session: Any = None,
    user_id: int = 0,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Any:
    """获取面向 ``root`` 的 :class:`ProjectVibeCoder`。

    内部复用 :func:`get_vibe_coder` 的 LLMClient,不再单独缓存
    (``VibeCoder.project_coder`` 已按 root 做了 per-instance 缓存)。
    """
    coder = get_vibe_coder(session=session, user_id=user_id, provider=provider, model=model)
    return coder.project_coder(root)


def reset_vibe_coder_cache() -> None:
    """清空缓存(测试 / 切换默认 LLM 时使用)。"""
    with _LOCK:
        _CODER_CACHE.clear()


# ---------------------------------------------------------------------------
# 租户路径边界
# ---------------------------------------------------------------------------


def _tenant_workspace_root(user_id: int) -> Path:
    """允许 vibe_edit/heal 操作的根目录。

    优先级:
    1. 环境变量 ``MODSTORE_TENANT_WORKSPACE_ROOT``(配 ``{user_id}`` 占位)
    2. ``MODSTORE_DATA_DIR/workspaces/{user_id}``
    3. ``./var/workspaces/{user_id}``
    """
    tpl = os.environ.get("MODSTORE_TENANT_WORKSPACE_ROOT", "").strip()
    if tpl:
        if "{user_id}" in tpl:
            tpl = tpl.replace("{user_id}", str(user_id or 0))
        return Path(tpl)
    base = os.environ.get("MODSTORE_DATA_DIR") or str(Path.cwd() / "var")
    return Path(base) / "workspaces" / str(user_id or 0)


def ensure_within_workspace(root: str | Path, *, user_id: int) -> Path:
    """校验 ``root`` 落在用户工作区内,否则抛 :class:`VibePathError`。

    放到本模块里以便所有 handler / adapter 复用同一边界。
    """
    if not root:
        raise VibePathError("缺少 root 参数")
    target = Path(root).resolve()
    workspace = _tenant_workspace_root(user_id).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise VibePathError(f"root={target!s} 不在用户工作区 {workspace!s} 下;拒绝执行") from exc
    if not target.exists():
        raise VibePathError(f"root={target!s} 不存在")
    return target


# ---------------------------------------------------------------------------
# 序列化 helper
# ---------------------------------------------------------------------------


def patch_to_dict(patch: Any) -> Dict[str, Any]:
    """``ProjectPatch.to_dict()`` 的安全调用:对老版本 fallback 到 ``vars``。"""
    if patch is None:
        return {}
    if hasattr(patch, "to_dict") and callable(patch.to_dict):
        return dict(patch.to_dict())
    return {k: v for k, v in vars(patch).items() if not k.startswith("_")}


def heal_result_to_dict(result: Any) -> Dict[str, Any]:
    """:class:`HealResult` → JSON-friendly dict;失败时返回 ``{"error": ...}``。"""
    if result is None:
        return {}
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return dict(result.to_dict())
    out: Dict[str, Any] = {}
    for attr in ("ok", "rounds", "final_patch", "tool_log", "error"):
        if hasattr(result, attr):
            value = getattr(result, attr)
            if attr == "final_patch" and value is not None:
                value = patch_to_dict(value)
            out[attr] = value
    return out


__all__ = [
    "ChatDispatchLLMClient",
    "VibeIntegrationError",
    "VibePathError",
    "ensure_within_workspace",
    "get_project_vibe_coder",
    "get_vibe_coder",
    "heal_result_to_dict",
    "patch_to_dict",
    "reset_vibe_coder_cache",
    "vibe_available",
]
