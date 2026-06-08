"""LLM 调用的薄抽象，方便单元测试用 ``StubLlmClient`` 替换。

主代码只用 :class:`LlmClient` 协议（``Protocol``），具体实例
:class:`RealLlmClient` 内部走 :func:`modstore_server.llm_chat_proxy.chat_dispatch`。

vibe-coding 接入后,``RealLlmClient.from_user_session`` 是新的推荐入口:
- 走 :func:`services.llm.chat_dispatch_via_session`,统一 BYOK / 平台 Key 解析与 quota 消耗。
- 与 :class:`modstore_server.integrations.vibe_adapter.ChatDispatchLLMClient`
  共用同一上游,避免脚本工作流和 vibe-coding 出现两套不一致的 LLM 解析。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Protocol

from modstore_server.script_agent.llm_output_sanitize import finalize_extracted_python

# Reasoning-heavy models often fill the completion budget with reasoning_* fields first.
# Keep these high enough that ``content`` still has room for full ``script.py``.
SCRIPT_AGENT_CODE_MAX_TOKENS = 16384
SCRIPT_AGENT_PLAN_MAX_TOKENS = 8192
SCRIPT_AGENT_REPAIR_MAX_TOKENS = 16384
SCRIPT_AGENT_JUDGE_MAX_TOKENS = 2048

_EMPTY_CONTENT_HINT = "未输出正文"


class LlmClient(Protocol):
    async def chat(self, messages: List[Dict[str, str]], *, max_tokens: int = 1024) -> str: ...


class RealLlmClient:
    """绑定到具体 provider/model/key 的真实 LLM 客户端。"""

    def __init__(
        self,
        provider: str,
        *,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        session: Any = None,
        user_id: int = 0,
        use_session_dispatch: bool = False,
        forbid_reasoning_fallback: bool = False,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._session = session
        self._user_id = int(user_id or 0)
        self._use_session_dispatch = bool(use_session_dispatch)
        self._forbid_reasoning_fallback = bool(forbid_reasoning_fallback)

    @classmethod
    def from_user_session(
        cls,
        session: Any,
        user_id: int,
        provider: str,
        model: str,
        *,
        forbid_reasoning_fallback: bool = False,
    ) -> "RealLlmClient":
        """走 ``llm_key_resolver`` 解析 BYOK,使用 session 路径调用。

        与 :class:`modstore_server.integrations.vibe_adapter.ChatDispatchLLMClient`
        是一对的两面:同一份解析规则、同一份 quota 消耗。
        """
        try:
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
        except Exception:  # pragma: no cover - resolver 缺失时降级
            api_key = ""
            base_url = None
        return cls(
            provider,
            api_key=api_key or "",
            model=model,
            base_url=base_url,
            session=session,
            user_id=int(user_id or 0),
            use_session_dispatch=True,
            forbid_reasoning_fallback=forbid_reasoning_fallback,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 1024,
    ) -> str:
        if self._use_session_dispatch and self._session is not None:
            dispatch = None  # session path uses chat_dispatch_via_session
        else:
            from modstore_server.llm_chat_proxy import chat_dispatch as _cd

            dispatch = _cd

        mt = max(32, int(max_tokens))
        last_err = ""
        for attempt in range(2):
            if self._use_session_dispatch and self._session is not None:
                from modstore_server.services.llm import chat_dispatch_via_session

                res = await chat_dispatch_via_session(
                    self._session,
                    self._user_id,
                    self.provider,
                    self.model,
                    messages,
                    max_tokens=mt,
                    forbid_reasoning_fallback=self._forbid_reasoning_fallback,
                )
            else:
                assert dispatch is not None
                res = await dispatch(
                    self.provider,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self.model,
                    messages=messages,
                    max_tokens=mt,
                    forbid_reasoning_fallback=self._forbid_reasoning_fallback,
                )
            if res.get("ok"):
                return str(res.get("content") or "")
            last_err = str(res.get("error") or res.get("status") or "")
            bump = (
                attempt == 0
                and self._forbid_reasoning_fallback
                and _EMPTY_CONTENT_HINT in last_err
                and mt < 32768
            )
            if bump:
                mt = min(mt * 2, 32768)
                continue
            raise RuntimeError(f"LLM 调用失败: {last_err}")
        raise RuntimeError(f"LLM 调用失败: {last_err}")


class StubLlmClient:
    """单测专用：按 FIFO 顺序返回预设回复。每次 ``chat`` 取队首。"""

    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 1024,
    ) -> str:
        await asyncio.sleep(0)  # 模拟 await
        self.calls.append({"messages": list(messages), "max_tokens": max_tokens})
        if not self._responses:
            raise AssertionError("StubLlmClient: 预设回复已耗尽")
        return self._responses.pop(0)


def _greedy_python_fence_span(raw: str) -> str:
    """From first `` ```python`` / `` ```py`` to the **last** `` ``` `` in ``raw``.

    LLMs often put Markdown code fences *inside* Python triple-quoted docstrings.
    The non-greedy regex ``([\\s\\S]*?)`` then stops at the **first** inner `` ``` ``,
    yielding a truncated fragment and ``SyntaxError: unterminated triple-quoted string``.
    Spanning to the outer closing fence fixes the common case.
    """
    m = re.search(r"```(?:python|py)\b\s*", raw, flags=re.I)
    if not m:
        return ""
    start = m.end()
    end = raw.rfind("```")
    if end < start:
        return raw[start:].strip()
    return raw[start:end].strip()


def _first_parseable_python(candidates: List[str]) -> Optional[str]:
    ok: List[str] = []
    for c in candidates:
        if not (c or "").strip():
            continue
        try:
            ast.parse(c)
            ok.append(c)
        except SyntaxError:
            continue
    if not ok:
        return None
    return max(ok, key=len)


def _extract_code_block_core(text: str, *, lang: str = "python") -> str:
    """Internal: extract fenced Python without reasoning-strip pass."""
    raw = (text or "").strip()
    if not raw:
        return ""

    wanted_langs = {lang.lower(), "python", "py", "python3"}
    python_fence_bodies: List[str] = []
    fenced_candidates: List[tuple[str, str]] = []
    for m in re.finditer(r"```([a-zA-Z0-9_+-]*)\s*([\s\S]*?)```", raw):
        label = (m.group(1) or "").strip().lower()
        body = (m.group(2) or "").strip()
        if not body:
            continue
        if label in wanted_langs:
            python_fence_bodies.append(body)
            continue
        if label in {"json", "js", "javascript"}:
            json_code = _extract_code_from_json(body)
            if json_code:
                return json_code
        fenced_candidates.append((label, body))

    if python_fence_bodies:
        greedy = _greedy_python_fence_span(raw)
        merged_candidates = list(python_fence_bodies)
        if greedy:
            merged_candidates.append(greedy)
        best = _first_parseable_python(merged_candidates)
        if best is not None:
            return best
        return max(merged_candidates, key=len)

    for label, body in fenced_candidates:
        if (not label or label in {"text", "plain"}) and _looks_like_python_source(body):
            return body
    for _label, body in fenced_candidates:
        if _looks_like_python_source(body):
            return body
    if fenced_candidates:
        return fenced_candidates[0][1]

    json_code = _extract_code_from_json(raw)
    if json_code:
        return json_code

    # 允许模型只输出了 opening/closing fence 的半结构文本。
    normalized = re.sub(r"^\s*```(?:python|py)?\s*", "", raw, flags=re.I)
    normalized = re.sub(r"\s*```\s*$", "", normalized, flags=re.I).strip()
    if not normalized:
        return ""

    # 没有 fenced block 时，优先剥离前置说明文字，避免 line 1 invalid syntax。
    lines = normalized.splitlines()
    first_code_line = next((i for i, ln in enumerate(lines) if _looks_like_python_line(ln)), None)
    if first_code_line is not None and first_code_line > 0:
        head_non_empty = next((ln.strip() for ln in lines if ln.strip()), "")
        if head_non_empty and not _looks_like_python_line(head_non_empty):
            candidate = "\n".join(lines[first_code_line:]).strip()
            if candidate:
                return candidate

    if _looks_like_python_source(normalized):
        return normalized

    if first_code_line is not None and first_code_line > 0:
        candidate = "\n".join(lines[first_code_line:]).strip()
        if candidate:
            return candidate

    return normalized


def extract_code_block(text: str, *, lang: str = "python") -> str:
    """尽量从 LLM 回答里提取纯代码，优先 Python fenced block。"""
    raw = _extract_code_block_core(text, lang=lang)
    cleaned, _warnings = finalize_extracted_python(raw)
    return cleaned


def _extract_code_from_json(text: str) -> str:
    try:
        payload = json.loads((text or "").strip())
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("code", "script", "script_py", "python"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _looks_like_python_source(text: str) -> bool:
    code = (text or "").strip()
    if not code:
        return False
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        lines = [ln for ln in code.splitlines() if ln.strip()]
        if not lines:
            return False
        marks = sum(1 for ln in lines[:12] if _looks_like_python_line(ln))
        return marks >= 2 or (marks >= 1 and len(lines) <= 2)


def _looks_like_python_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if s.startswith(("#", "@", "'''", '"""', "'", '"')):
        return True
    starters = (
        "from ",
        "import ",
        "def ",
        "class ",
        "if ",
        "for ",
        "while ",
        "try:",
        "with ",
        "async ",
        "return ",
        "raise ",
        "yield ",
        "pass",
        "break",
        "continue",
        "print(",
    )
    if any(s.startswith(p) for p in starters):
        return True
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", s))
