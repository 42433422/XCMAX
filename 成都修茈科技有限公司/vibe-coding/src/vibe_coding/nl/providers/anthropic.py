"""Anthropic Claude adapter.

Claude's API isn't OpenAI-compatible (different endpoint, different
``messages`` shape, no ``response_format`` knob), so this adapter
implements the wire format directly instead of inheriting from
:class:`OpenAICompatibleLLM`.

JSON-mode is implemented via prompt instruction + a tail-stripping
post-process: when ``json_mode=True`` we append a "respond ONLY with
JSON" reminder to the system prompt and try to extract the first
``{ … }`` block from the response. Use the tolerant
:func:`vibe_coding.nl.parsing.safe_parse_json_object` downstream
to be safe.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..llm import LLMError


class AnthropicLLM:
    """Claude (Anthropic) chat client over the public Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-3-5-sonnet-latest",
        *,
        base_url: str = "https://api.anthropic.com/v1",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        anthropic_version: str = "2023-06-01",
        timeout_s: float = 60.0,
        verify_ssl: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.anthropic_version = anthropic_version
        self.timeout_s = float(timeout_s)
        self.verify_ssl = bool(verify_ssl)

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
        sys_prompt = system
        if json_mode:
            sys_prompt = (
                system.rstrip()
                + "\n\nIMPORTANT: respond with **valid JSON only**, no Markdown fences."
            )
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user}],
            "temperature": self.temperature,
        }
        payload = self._post("/messages", body)
        content = self._extract_text(payload)
        if not content:
            raise LLMError("AnthropicLLM returned empty content")
        if json_mode:
            content = _trim_to_first_json_block(content) or content
        return content

    # ----------------------------------------------------- helpers

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.anthropic_version,
            },
        )
        try:
            ctx = self._ssl_context()
            with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            text = ""
            if exc.fp is not None:
                try:
                    text = exc.fp.read().decode("utf-8", errors="replace")
                except OSError:
                    text = ""
            raise LLMError(f"AnthropicLLM HTTP {exc.code}: {text[:300]}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"AnthropicLLM network error: {exc.reason}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"AnthropicLLM non-JSON response: {raw[:200]!r}") from exc

    def _extract_text(self, payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    parts.append(str(chunk.get("text") or ""))
            return "\n".join(parts).strip()
        return ""

    def _ssl_context(self):
        if self.verify_ssl:
            return None
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def _trim_to_first_json_block(text: str) -> str:
    """Best-effort: strip Markdown fences and prose before the first ``{``.

    Claude occasionally wraps JSON in ``\u200b`` chatter; this helper
    yields the substring starting from the first balanced object so the
    downstream :func:`safe_parse_json_object` can do its job.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        # strip optional language hint
        nl = s.find("\n")
        if nl >= 0:
            s = s[nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    start = s.find("{")
    if start < 0:
        return s
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s


__all__ = ["AnthropicLLM"]
