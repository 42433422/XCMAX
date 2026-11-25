"""The fixed local executor's deployment contract and independent model route.

New tasks use Codex. Missing qualification blocks admission; it never selects a
retired model/tool loop. Previously persisted business graphs retain their own
host-owned continuation path.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from app.utils.security.safe_download_path import resolve_under_allowed_dirs

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
    # A completed first step must be read back before the dependent second step
    # is executed in the resumed process, then independently verified again.
    "multi_step_restart_continuation",
)


class RuntimePolicyError(ValueError):
    """A configured runtime is unavailable or has not been qualified."""

    public_message = "运行配置尚未通过核验，请检查模型设置或联系部署管理员。"


def qualification_host_identity() -> dict[str, str]:
    """Bind evidence to the actual host source and platform, not mutable rollout metadata."""
    from app.build_identity import verified_source_sha

    try:
        sha = verified_source_sha()
    except ValueError as exc:
        raise RuntimePolicyError(
            "Runtime host build identity is unavailable or inconsistent"
        ) from exc
    return {"git_sha": sha, "system": platform.system(), "machine": platform.machine()}


class QualificationUpgradeRequired(RuntimePolicyError):
    """The exact route passed older checks but needs the new real probe once."""


class _DefaultResponseModel(str):
    """Distinguish an omitted model binding from an explicitly invalid empty one."""


_DEFAULT_RESPONSE_MODEL = _DefaultResponseModel()


def _read_evidence(path: Path, root: Path, maximum: int) -> bytes:
    """Bound and hash the same regular-file snapshot, rejecting redirected paths."""
    try:
        if not path.is_absolute() or not root.is_absolute() or root.is_symlink():
            raise ValueError("invalid evidence path")
        relative = path.relative_to(root)
        if ".." in relative.parts:
            raise ValueError("invalid evidence path")
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("redirected evidence path")
            if parent == root:
                break
        safe = resolve_under_allowed_dirs(str(path), [root])
        descriptor = os.open(
            safe, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise ValueError("invalid evidence file")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            named = safe.lstat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if (
                len(raw) > maximum
                or not stat.S_ISREG(named.st_mode)
                or any(getattr(before, key) != getattr(after, key) for key in fields)
                or any(getattr(after, key) != getattr(named, key) for key in fields)
                or safe.resolve() != safe
            ):
                raise ValueError("evidence changed during read")
        return raw
    except (OSError, ValueError) as exc:
        raise RuntimePolicyError("Runtime qualification evidence cannot be verified") from exc


def _verify_evidence(receipt: dict, certificate: Path) -> None:
    refs, digests = receipt["evidence_refs"], receipt.get("evidence_sha256")
    if (
        not 1 <= len(refs) <= 8
        or len(set(refs)) != len(refs)
        or not isinstance(digests, dict)
        or set(digests) != set(refs)
    ):
        raise RuntimePolicyError("Runtime qualification evidence digests are missing")
    for ref in refs:
        raw = _read_evidence(Path(ref), certificate.parent, 1_048_576)
        if hashlib.sha256(raw).hexdigest() != digests[ref]:
            raise RuntimePolicyError("Runtime qualification evidence digest mismatch")
        try:
            evidence = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise RuntimePolicyError("Runtime qualification evidence cannot be decoded") from exc
        if (
            not isinstance(evidence, dict)
            or evidence.get("schema") != "xcmax.runtime-qualification-evidence.v1"
            or evidence.get("ok") is not True
            or any(
                evidence.get(key) != receipt[key]
                for key in ("route_identity", "host_identity", "codex_version", "checks")
            )
        ):
            raise RuntimePolicyError("Runtime qualification evidence binding mismatch")


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
    gateway_kind: Literal["responses", "litellm", "market"] = "responses"
    # Account credentials stay in the current request, never in persisted metadata.
    credential: str = field(default="", repr=False, compare=False)
    route_token: str = field(default="", repr=False, compare=False)
    config_revision: str = ""
    key_source: str = ""

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
        if type(self.gateway_kind) is not str or self.gateway_kind not in {
            "responses",
            "litellm",
            "market",
        }:
            raise RuntimePolicyError("gateway_kind must be responses, litellm or market")
        if self.gateway_kind == "market":
            for name in ("credential", "route_token", "config_revision", "key_source"):
                value = getattr(self, name)
                if (
                    not isinstance(value, str)
                    or not value
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)
                ):
                    raise RuntimePolicyError(
                        "Authenticated account runtime configuration is incomplete"
                    )
            if self.api_key_env:
                raise RuntimePolicyError(
                    "Account runtime credentials cannot use process environment"
                )
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
        if self.gateway_kind == "market":
            values.update(config_revision=self.config_revision, key_source=self.key_source)
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    def token(self) -> str:
        if self.gateway_kind == "market":
            return self.credential
        if not self.api_key_env:
            if urlsplit(self.base_url).hostname not in {"127.0.0.1", "::1", "localhost"}:
                raise RuntimePolicyError("Remote gateway credential is not configured")
            return ""
        value = os.environ.get(self.api_key_env, "").strip()
        if not value:
            raise RuntimePolicyError("Configured gateway credential is unavailable")
        return value

    def headers(self, request_id: str) -> dict[str, str]:
        """Bind the original account snapshot and one outbound request identity."""
        token = self.token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if self.gateway_kind == "market":
            headers.update({"X-XCMax-Route-Token": self.route_token, "Idempotency-Key": request_id})
        return headers

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
            **(
                {"config_revision": self.config_revision, "key_source": self.key_source}
                if self.gateway_kind == "market"
                else {}
            ),
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
            receipt = json.loads(
                _read_evidence(self.qualification_file, self.qualification_file.parent, 65_536)
            )
        except (OSError, ValueError) as exc:
            raise RuntimePolicyError("Codex gateway qualification cannot be read") from exc
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != "xcmax.runtime-qualification.v1"
            or receipt.get("route_identity") != self.route.identity
            or receipt.get("codex_version") != CODEX_VERSION
            or receipt.get("host_identity") != qualification_host_identity()
            or receipt.get("model_kind") != "real"
            or not isinstance(receipt.get("evidence_refs"), list)
            or not receipt["evidence_refs"]
            or any(not isinstance(ref, str) or not ref.strip() for ref in receipt["evidence_refs"])
            or not isinstance(receipt.get("checks"), dict)
            or any(receipt["checks"].get(key) != "PASS" for key in QUALIFICATION_CHECKS[:-1])
        ):
            raise RuntimePolicyError("Exact route has not passed independent runtime qualification")
        _verify_evidence(receipt, self.qualification_file)
        if QUALIFICATION_CHECKS[-1] not in receipt["checks"]:
            raise QualificationUpgradeRequired(
                "Exact route requires multi-step runtime qualification"
            )
        if receipt["checks"][QUALIFICATION_CHECKS[-1]] != "PASS":
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
