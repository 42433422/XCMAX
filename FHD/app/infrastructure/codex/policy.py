"""The fixed local executor's deployment contract and independent model route.

New tasks use Codex. Missing qualification blocks admission; it never selects a
retired model/tool loop. Previously persisted business graphs retain their own
host-owned continuation path.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

CODEX_VERSION = "0.171.0"
QUALIFICATION_CHECKS = (
    "responses_stream",
    "multi_turn_tools",
    "openai_network_denied",
    "business_receipt_verified",
    # These require observed upstream evidence, not merely a pinned request.model.
    "upstream_failover_disabled",
    "response_model_identity",
    # One real run on this exact route/version must force local compaction,
    # restart the runtime, resume the same task and prove no effect was replayed.
    "forced_compaction_restart_same_task_no_replay",
)


class RuntimePolicyError(ValueError):
    """A configured runtime is unavailable or has not been qualified."""


class _DefaultResponseModel(str):
    """Distinguish an omitted model binding from an explicitly invalid empty one."""


_DEFAULT_RESPONSE_MODEL = _DefaultResponseModel()


def _positive(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise RuntimePolicyError(f"Invalid runtime {name}")
    return value


def independent_gateway_url(raw: str) -> str:
    url = urlsplit(raw)
    host = (url.hostname or "").lower().rstrip(".")
    if (
        not host
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.scheme not in {"http", "https"}
        or (url.scheme == "http" and host not in {"127.0.0.1", "::1", "localhost"})
        or any(
            host == domain or host.endswith("." + domain)
            for domain in ("openai.com", "chatgpt.com", "openai.azure.com")
        )
    ):
        raise RuntimePolicyError("Codex requires an explicit independent HTTPS or loopback gateway")
    return raw.rstrip("/")


@dataclass(frozen=True)
class ModelRoute:
    base_url: str
    model: str
    provider_id: str
    upstream_vendor: str
    context_window: int
    max_output_tokens: int
    api_key_env: str = field(default="", repr=False)
    max_model_calls: int = 24
    max_request_bytes: int = 4_194_304
    response_model: str = _DEFAULT_RESPONSE_MODEL
    failover_policy: Literal["disabled"] = "disabled"
    gateway_kind: Literal["responses", "litellm"] = "responses"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", independent_gateway_url(self.base_url))
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.model, self.provider_id, self.upstream_vendor)
        ) or not isinstance(self.api_key_env, str):
            raise RuntimePolicyError("An explicit model, provider and upstream vendor are required")
        if self.response_model is _DEFAULT_RESPONSE_MODEL:
            object.__setattr__(self, "response_model", self.model)
        if (
            type(self.response_model) is not str
            or not self.response_model
            or any(
                char.isspace() or ord(char) < 32 or ord(char) == 127 for char in self.response_model
            )
        ):
            raise RuntimePolicyError("response_model must be one exact nonempty model identity")
        if type(self.failover_policy) is not str or self.failover_policy != "disabled":
            raise RuntimePolicyError("Runtime upstream failover must be disabled")
        if type(self.gateway_kind) is not str or self.gateway_kind not in {"responses", "litellm"}:
            raise RuntimePolicyError("gateway_kind must be responses or litellm")
        if self.upstream_vendor.strip().lower() in {"openai", "azure-openai", "azure_openai"}:
            raise RuntimePolicyError("The independent runtime cannot require an OpenAI model")
        for name, maximum in (
            ("context_window", 10_000_000),
            ("max_output_tokens", 1_000_000),
            ("max_model_calls", 1000),
            ("max_request_bytes", 16_777_216),
        ):
            _positive(getattr(self, name), name, maximum)
        if self.max_output_tokens >= self.context_window:
            raise RuntimePolicyError("Output capacity must leave room for model input")

    @property
    def identity(self) -> str:
        values = {
            key: getattr(self, key)
            for key in (
                "base_url",
                "model",
                "provider_id",
                "upstream_vendor",
                "context_window",
                "max_output_tokens",
                "max_model_calls",
                "max_request_bytes",
                "response_model",
                "failover_policy",
                "gateway_kind",
            )
        }
        values["codex_version"] = CODEX_VERSION
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def token(self) -> str:
        if not self.api_key_env:
            if urlsplit(self.base_url).hostname not in {"127.0.0.1", "::1", "localhost"}:
                raise RuntimePolicyError("Remote gateway credential is not configured")
            return ""
        value = os.environ.get(self.api_key_env, "").strip()
        if not value:
            raise RuntimePolicyError("Configured gateway credential is unavailable")
        return value

    def runtime_identity(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "route_identity": self.identity,
            "model": self.model,
            "response_model": self.response_model,
            "failover_policy": self.failover_policy,
            "gateway_kind": self.gateway_kind,
            "upstream_vendor": self.upstream_vendor,
            "independent": True,
            "max_model_calls": self.max_model_calls,
        }


@dataclass(frozen=True)
class RuntimeSettings:
    engine: str = "codex"
    surfaces: tuple[str, ...] = ("chat", "employee")
    route: ModelRoute | None = None
    runtime_root: Path | None = None
    codex_bin: str | None = None
    turn_timeout_seconds: int = 180
    qualification_file: Path | None = None

    def require_qualified(self) -> ModelRoute:
        if self.route is None or self.qualification_file is None:
            raise RuntimePolicyError(
                "Codex gateway qualification is missing; runtime was not started"
            )
        try:
            receipt = json.loads(self.qualification_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError("Codex gateway qualification cannot be read") from exc
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != "xcmax.runtime-qualification.v1"
            or receipt.get("route_identity") != self.route.identity
            or receipt.get("codex_version") != CODEX_VERSION
            or receipt.get("model_kind") != "real"
            or not isinstance(receipt.get("evidence_refs"), list)
            or not receipt["evidence_refs"]
            or any(not isinstance(ref, str) or not ref.strip() for ref in receipt["evidence_refs"])
            or not isinstance(receipt.get("checks"), dict)
            or any(receipt["checks"].get(key) != "PASS" for key in QUALIFICATION_CHECKS)
        ):
            raise RuntimePolicyError("Exact route has not passed independent runtime qualification")
        return self.route


def runtime_settings() -> RuntimeSettings:
    location = os.environ.get("XCAGI_AGENT_RUNTIME_CONFIG", "").strip()
    if not location:
        return RuntimeSettings()
    try:
        data = json.loads(Path(location).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected object")
        engine = data.get("engine", "codex")
        if engine != "codex":
            raise RuntimePolicyError(
                "Native agent loops are retired; configure the fixed Codex executor"
            )
        surfaces = data.get("surfaces", ["chat", "employee"])
        if not isinstance(surfaces, list) or sorted(surfaces) != ["chat", "employee"]:
            raise RuntimePolicyError("The fixed executor must own both chat and employee tasks")
        route = ModelRoute(**data["route"])
        root = Path(data["runtime_root"]).expanduser() if data.get("runtime_root") else None
        if root is None or not root.is_absolute():
            raise RuntimePolicyError("Codex requires an absolute private runtime_root")
        return RuntimeSettings(
            engine=engine,
            surfaces=tuple(surfaces),
            route=route,
            runtime_root=root,
            codex_bin=data.get("codex_bin"),
            turn_timeout_seconds=_positive(data.get("turn_timeout_seconds", 180), "timeout", 3570),
            qualification_file=Path(data["qualification_file"])
            if data.get("qualification_file")
            else None,
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, RuntimePolicyError):
            raise
        raise RuntimePolicyError("Agent runtime deployment configuration is invalid") from exc
