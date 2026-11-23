"""Adapt the authenticated account's existing model selection to the fixed runtime.

The platform remains the model/credential source. Only public route identity and
local qualification evidence are durable; account and route tokens stay in memory.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from app.application.market_llm.authentication import validate_demo_destination
from app.application.market_llm.protocols import Connection, PreparedChatRoute
from app.application.market_llm.routing import resolve_account_route
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimePolicyError,
    RuntimeSettings,
)
from app.infrastructure.modstore_transport import MarketModelError, httpx_sync_client
from app.utils.path_io.path_utils import get_desktop_state_dir

_QUALIFICATION_ERRORS = {
    "runtime_qualification_required": "当前路由的运行验收尚未完成。",
    "runtime_qualification_failed": "当前模型尚未通过独立运行验收。",
    "runtime_qualification_unavailable": "本机 Codex 运行组件不可用，请检查安装。",
    "runtime_qualification_evidence_missing": "模型的流式、工具、压缩或恢复检查尚未全部通过。",
    "runtime_qualification_config_invalid": "本机运行验收目录无效，请检查私有数据目录。",
    "runtime_qualification_limit": "运行验收已达到调用或响应上限。",
    "runtime_billing_evidence_missing": "无法核对模型计费回执，请检查平台模型计费配置。",
    "runtime_usage_evidence_missing": "模型未返回有效用量，请检查网关的用量回执。",
    "runtime_network_denial_unverified": "模型出口访问限制未通过检查，请检查本机运行组件。",
    "runtime_upstream_attempts_unverified": "无法核实固定上游且关闭备用路由，请检查模型网关配置。",
    "runtime_stream_evidence_missing": "模型未通过 Responses 流式协议检查。",
    "runtime_model_identity_mismatch": "模型响应标识与已保存的上游配置不一致。",
    "runtime_model_response_failed": "模型响应失败，请检查已保存的模型配置。",
    "runtime_model_probe_failed": "模型验收请求未完成，请检查模型网关连接。",
    "runtime_probe_turn_failed": "固定执行器未完成工具调用或原任务恢复检查。",
    "runtime_probe_receipt_missing": "无法核验隔离测试的实际操作回执。",
}


class RuntimeSetupError(RuntimePolicyError):
    def __init__(self, code: str, message: str, *, checks: dict | None = None):
        self.code = code
        self.checks = checks or {}
        super().__init__(message)


def _qualification_failure(result: dict) -> RuntimeSetupError:
    code = result.get("error_code")
    if not isinstance(code, str) or code not in _QUALIFICATION_ERRORS:
        code = "runtime_qualification_required"
    raw_checks = result.get("checks") or {}
    checks = {
        name: raw_checks[name]
        for name in QUALIFICATION_CHECKS
        if isinstance(raw_checks, dict) and raw_checks.get(name) in ("PASS", "FAIL")
    }
    return RuntimeSetupError(
        code,
        _QUALIFICATION_ERRORS[code]
        + "修复后可在模型设置中重新运行验收，或使用 xcagi-brain --timeout 600 runtime-check --retry。",
        checks=checks,
    )


def _account_connection(owner: str) -> Connection:
    """Use a real login scope, never the conversation ID or an unscoped token."""
    from app.domain.context.current_request import get_current_request
    from app.domain.shared_services.conversation.modstore_adapter import (
        ModstorePlatformAdapter,
        create_modstore_openai_client_from_request,
    )

    request = get_current_request()
    if request is not None:
        from app.application.market_llm.authentication import load_session_ports

        sessions = load_session_ports()
        session_owner = sessions.owner(sessions.session_id(request))
        if str(session_owner) != owner:
            raise RuntimeSetupError(
                "runtime_login_required", "当前登录身份已变化，请重新登录后继续原任务。"
            )
        client = create_modstore_openai_client_from_request(request)
    else:
        # A scoped client alone does not prove which local owner owns its token.
        # Background workers refresh credentials only through the verified owner.
        from app.fastapi_routes.market_account import latest_session_market_token

        token = latest_session_market_token(user_id=int(owner))
        if not token:
            raise RuntimeSetupError(
                "runtime_login_required", "当前账号的模型登录已失效，请重新登录。"
            )
        adapter = ModstorePlatformAdapter.from_session(auth_token=token)
        adapter.user_id = None
        return adapter._connection()
    if getattr(client, "is_modstore_openai_compatible", False) is not True:
        raise RuntimeSetupError(
            "runtime_account_model_required",
            "请在模型设置中选择当前账号可用的平台模型或自带密钥模型。",
        )
    connection = client.adapter._connection()
    if not connection.auth_token:
        raise RuntimeSetupError("runtime_login_required", "当前账号的模型登录已失效，请重新登录。")
    return connection


def _model_route(prepared: PreparedChatRoute) -> ModelRoute:
    prepared.assert_valid(prepared.connection)
    snapshot = prepared.snapshot
    runtime = snapshot.get("runtime")
    capacities = snapshot.get("model_capabilities") or {}
    if (
        not isinstance(runtime, dict)
        or runtime.get("schema") != "xcmax.codex-route.v1"
        or runtime.get("codex_version") != CODEX_VERSION
        or runtime.get("gateway_kind") != "market"
        or runtime.get("failover_policy") != "disabled"
        or any(
            key not in runtime
            for key in ("upstream_vendor", "response_model", "max_model_calls", "max_request_bytes")
        )
        or not isinstance(snapshot.get("route_token"), str)
        or not snapshot["route_token"]
        or not snapshot.get("config_revision")
        or snapshot.get("key_source") not in {"platform", "user_override"}
        or not isinstance(capacities, dict)
        or any(
            type(capacities.get(key)) is not int for key in ("context_window", "max_output_tokens")
        )
    ):
        raise RuntimeSetupError(
            "runtime_configuration_required",
            "当前模型缺少 Codex 运行信息，请在模型设置中核对上游模型、容量和 Responses 支持。",
        )
    try:
        return ModelRoute(
            base_url=prepared.connection.platform_url.rstrip("/") + "/v1",
            model="/".join(prepared.route),
            provider_id=prepared.route[0],
            upstream_vendor=runtime["upstream_vendor"],
            response_model=runtime["response_model"],
            context_window=capacities["context_window"],
            max_output_tokens=capacities["max_output_tokens"],
            max_model_calls=runtime["max_model_calls"],
            max_request_bytes=runtime["max_request_bytes"],
            gateway_kind="market",
            credential=prepared.connection.auth_token,
            route_token=snapshot["route_token"],
            config_revision=str(snapshot["config_revision"]),
            key_source=snapshot["key_source"],
        )
    except RuntimePolicyError as exc:
        raise RuntimeSetupError(
            "runtime_configuration_required",
            "当前模型的独立运行配置无效，请在模型设置中核对并保存。",
        ) from exc


def _private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeSetupError(
            "runtime_storage_invalid", "运行状态目录不是独立私有目录，请检查本机数据目录。"
        )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _qualified_settings(
    settings: RuntimeSettings, *, owner_scope: str, evidence: dict, retry: bool = False
) -> tuple[RuntimeSettings, bool]:
    """One bounded attempt per exact account/route, serialized with existing filelock."""
    from app.infrastructure.codex.qualification import qualify_runtime

    qualification = settings.qualification_file
    route = settings.route
    assert qualification is not None and route is not None
    attempt = qualification.with_name("setup-attempt.json")
    lock = qualification.with_name("setup.lock")
    if any(path.is_symlink() for path in (qualification, attempt, lock)):
        raise RuntimeSetupError("runtime_storage_invalid", "运行验收目录无效，请检查本机数据目录。")
    try:
        with FileLock(lock, timeout=0, mode=0o600):
            try:
                settings.require_qualified()
                return settings, False
            except RuntimePolicyError:
                pass  # Only the real runner may produce the missing qualification.
            if attempt.exists() and not retry:
                try:
                    previous = json.loads(attempt.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    previous = {}
                raise _qualification_failure(previous if isinstance(previous, dict) else {})
            # Write before any model call, including process interruption or crash.
            attempt.write_text(
                json.dumps({"state": "started", "route_identity": route.identity}),
                encoding="utf-8",
            )
            attempt.chmod(0o600)
            from app.infrastructure.chat_stream_lifetime import publish_stream_note

            publish_stream_note(
                "正在验收当前账号的模型与本机执行器，首次验收可能需要数分钟；通过后继续处理本轮请求。"
            )
            result = qualify_runtime(settings, owner_scope=owner_scope, upstream_evidence=evidence)
            failure = _qualification_failure(result)
            attempt.write_text(
                json.dumps(
                    {
                        "state": "passed" if result.get("ok") else "failed",
                        "route_identity": route.identity,
                        "error_code": failure.code if result.get("ok") is not True else None,
                        "checks": failure.checks,
                    }
                ),
                encoding="utf-8",
            )
            if result.get("ok") is not True:
                raise failure
            settings.require_qualified()
            return settings, True
    except Timeout as exc:
        raise RuntimeSetupError(
            "runtime_qualification_in_progress", "当前账号的模型正在完成首次运行验收，请稍后继续。"
        ) from exc


def _prepared_route(connection: Connection, selected: tuple[str, str] | None) -> PreparedChatRoute:
    try:
        snapshot = resolve_account_route(connection, httpx_sync_client, selected, runtime="codex")
    except MarketModelError as exc:
        message = {
            "CODEX_MODEL_UNSUPPORTED": "当前模型地址或密钥协议不支持独立运行，请在已有模型设置中核对模型服务。",
            "CODEX_MODEL_METADATA_REQUIRED": "当前模型缺少已确认的独立上游厂商和真实模型标识，请在模型设置中核对。",
            "CODEX_MODEL_CAPACITY_REQUIRED": "当前模型缺少有效的上下文容量和最大输出量，请在模型设置中补全。",
            "CODEX_ROUTE_SIGNING_UNAVAILABLE": "平台暂时无法签发当前账号的模型路由，请联系管理员检查模型网关配置。",
        }.get(exc.code or "", str(exc))
        raise RuntimeSetupError("runtime_configuration_required", message) from exc
    return PreparedChatRoute(connection, (snapshot["provider"], snapshot["model"]), snapshot)


def get_account_runtime_settings(
    owner: str,
    *,
    previous: dict[str, Any] | None = None,
    retry: bool = False,
    qualify: bool = True,
) -> RuntimeSettings:
    """Called only after the gateway verifies the actor and any existing task owner."""
    connection = _account_connection(owner)
    validate_demo_destination(connection)
    selected = None
    if previous:
        provider, model = previous.get("provider_id"), previous.get("model")
        if (
            previous.get("gateway_kind") != "market"
            or not isinstance(provider, str)
            or not isinstance(model, str)
        ):
            raise RuntimeSetupError(
                "runtime_changed", "原任务的模型路由不能改变，请恢复原部署配置。"
            )
        selected = provider, model.removeprefix(provider + "/")
    prepared = _prepared_route(connection, selected)
    route = _model_route(prepared)
    if previous and previous.get("route_identity") != route.identity:
        raise RuntimeSetupError(
            "runtime_changed", "原任务的模型配置已变化，请恢复原路由后继续；任务和回执已保留。"
        )
    scope = hashlib.sha256((connection.platform_url + "\0" + owner).encode()).hexdigest()
    root = _private_directory(
        Path(get_desktop_state_dir()).expanduser().resolve() / "codex-runtime"
    )
    root = _private_directory(root / scope)
    qualifications = _private_directory(root / "qualifications")
    evidence_root = _private_directory(qualifications / route.identity)
    settings = RuntimeSettings(
        route=route,
        runtime_root=root,
        qualification_file=evidence_root / "qualification.json",
    )
    if not qualify:
        return settings  # Staging freezes the route without paid model calls.
    settings, fresh = _qualified_settings(
        settings, owner_scope=scope, evidence=prepared.snapshot["runtime"], retry=retry
    )
    if fresh:
        # Qualification can consume most of the short-lived route-token TTL.
        # Refresh the same snapshot before business execution, never the default.
        refreshed = _model_route(_prepared_route(connection, prepared.route))
        if refreshed.identity != route.identity:
            raise RuntimeSetupError(
                "runtime_changed",
                "验收期间模型配置已变化，请重新读取模型设置；本轮未启动业务执行。",
            )
        settings = replace(settings, route=refreshed)
    return settings
