"""Generic OpenAI-compatible HTTP client.

Most modern hosted-model APIs (Qwen / Zhipu / Moonshot / DeepSeek /
together.ai / vLLM / ollama / LMStudio / …) expose an OpenAI-compatible
``/v1/chat/completions`` endpoint. This client speaks that contract
with **no SDK dependency** — pure ``urllib`` so vibe-coding's core
stays zero-deps.

Subclasses can override:

- :attr:`default_base_url` — vendor's hostname.
- :attr:`json_mode_field` — some vendors don't honour ``response_format``;
  set ``json_mode_field=""`` to skip it (the prompt should already say
  "return JSON").
- :meth:`build_messages` — for vendors that require an extra ``role``
  preamble or shaped tool-calling schema.
- :meth:`extract_content` — to handle non-standard response shapes.

Errors are normalised into :class:`LLMError` with the HTTP status code
and a short body excerpt so debugging stays cheap.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..llm import LLMError


class OpenAICompatibleLLM:
    """OpenAI-compatible chat-completions client over ``urllib``."""

    #: Default endpoint root; override per vendor in subclasses.
    default_base_url: str = "https://api.openai.com/v1"
    #: Field name used to request structured JSON. Vendors that lack it
    #: should set this to "" and rely on prompt instructions instead.
    json_mode_field: str = "response_format"
    #: HTTP timeout in seconds for a single chat call.
    request_timeout_s: float = 60.0
    #: Header to use for the API key. ``Authorization: Bearer …`` for most.
    auth_header_name: str = "Authorization"
    auth_header_template: str = "Bearer {api_key}"
    #: Some Chinese vendors require a per-request additional header
    #: (e.g. DashScope's ``X-DashScope-SSE``); subclasses override.
    extra_headers: dict[str, str] = {}

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        verify_ssl: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.temperature = float(temperature)
        self.max_tokens = max_tokens
        self.timeout_s = float(timeout_s or self.request_timeout_s)
        self.verify_ssl = bool(verify_ssl)

    # ------------------------------------------------------------------ chat

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
        body = {
            "model": self.model,
            "messages": self.build_messages(system, user),
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            body["max_tokens"] = int(self.max_tokens)
        if json_mode and self.json_mode_field:
            body[self.json_mode_field] = {"type": "json_object"}
        body = self.transform_request(body, system=system, user=user, json_mode=json_mode)
        payload = self._post("/chat/completions", body)
        content = self.extract_content(payload)
        if not content:
            raise LLMError(f"{type(self).__name__} returned empty content")
        return content

    # ---------------------------------------------------- subclass hooks

    def build_messages(self, system: str, user: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def transform_request(
        self,
        body: dict[str, Any],
        *,
        system: str,
        user: str,
        json_mode: bool,
    ) -> dict[str, Any]:
        """Last-chance hook for vendor-specific tweaks (e.g. tool schemas)."""
        return body

    def extract_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        first = choices[0] or {}
        msg = first.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        # Some providers return a list of content parts (Anthropic-flavoured
        # extensions) — concatenate textual chunks.
        if isinstance(content, list):
            parts: list[str] = []
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    parts.append(str(chunk.get("text") or ""))
                elif isinstance(chunk, str):
                    parts.append(chunk)
            return "\n".join(parts).strip()
        return ""

    # ---------------------------------------------------- HTTP plumbing

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            self.auth_header_name: self.auth_header_template.format(api_key=self.api_key),
        }
        for k, v in self.extra_headers.items():
            headers[k] = v
        req = urllib.request.Request(url=url, data=data, method="POST", headers=headers)
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
            raise LLMError(f"{type(self).__name__} HTTP {exc.code}: {text[:300]}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"{type(self).__name__} network error: {exc.reason}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"{type(self).__name__} non-JSON response: {raw[:200]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise LLMError(f"{type(self).__name__} expected object, got: {type(payload).__name__}")
        return payload

    def _ssl_context(self):
        if self.verify_ssl:
            return None
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


__all__ = ["OpenAICompatibleLLM"]
