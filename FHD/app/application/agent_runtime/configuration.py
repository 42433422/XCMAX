"""Qualify the existing account or deployment model route for the fixed runtime.

The platform remains the model/credential source. Only public route identity and
local qualification evidence are durable; account and route tokens stay in memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock, Timeout

from app.application.agent_runtime.runtime_error_surface import (
    public_runtime_failure as public_runtime_failure,
)
from app.application.market_llm.authentication import validate_demo_destination
from app.application.market_llm.protocols import Connection, PreparedChatRoute
from app.application.market_llm.routing import resolve_account_route
from app.infrastructure.xiaox.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    QualificationUpgradeRequired,
    RuntimePolicyError,
    RuntimeSettings,
    qualification_host_identity,
    runtime_settings,
)
from app.infrastructure.xiaox.transport import _write_private
from app.infrastructure.modstore_transport import MarketModelError, httpx_sync_client
from app.utils.path_io.path_utils import get_desktop_state_dir

_ROUTE_READ_ATTEMPTS = 3

_QUALIFICATION_ERRORS = {
    "runtime_qualification_required": "当前路由的运行验收尚未完成。",
    "runtime_qualification_failed": "当前模型尚未通过独立运行验收。",
    "runtime_qualification_unavailable": "本机 Xiaox 运行组件不可用，请检查安装。",
    "runtime_qualification_evidence_missing": "模型的流式、工具、压缩或恢复检查尚未全部通过。",
    "runtime_qualification_config_invalid": "本机运行验收目录无效，请检查私有数据目录。",
    "runtime_qualification_limit": "运行验收已达到调用或响应上限。",
    "runtime_qualification_interrupted": "上次运行验收已中断，调用结果尚未核清，请确认后重新验收。",
    "runtime_host_changed": "验收期间本机版本已变化，请重启应用后重新验收。",
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
        self.public_message = message
        super().__init__(message)


def _qualification_failure(result: dict, *, retry_hint: str | None = None) -> RuntimeSetupError:
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
        + (
            retry_hint
            or "修复后可在模型设置中重新运行验收，或使用 xcagi-brain --timeout 600 runtime-check --retry。"
        ),
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
        # 平台模型快照仍可能下发历史 schema 标识，两者都表示同一 Responses 路由。
        or runtime.get("schema") not in {"xcmax.xiaox-route.v1", "xcmax.codex-route.v1"}
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
            "当前模型缺少 Xiaox 运行信息，请在模型设置中核对上游模型、容量和 Responses 支持。",
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
    try:
        if path.is_symlink():
            raise RuntimeSetupError(
                "runtime_storage_invalid", "运行状态目录不是独立私有目录，请检查本机数据目录。"
            )
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.chmod(0o700)
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "运行状态目录无法写入，请检查本机数据目录权限。"
        ) from exc
    return path


def _qualified_settings(
    settings: RuntimeSettings,
    *,
    owner_scope: str,
    evidence: dict,
    retry: bool = False,
    retry_hint: str | None = None,
) -> tuple[RuntimeSettings, bool]:
    """One bounded attempt per exact owner/route, serialized with existing filelock."""
    from app.infrastructure.xiaox.qualification import qualify_runtime

    qualification = settings.qualification_file
    route = settings.route
    assert qualification is not None and route is not None
    attempt = qualification.with_name("setup-attempt.json")
    lock = qualification.with_name("setup.lock")
    try:
        if any(path.is_symlink() for path in (qualification, attempt, lock)):
            raise RuntimeSetupError(
                "runtime_storage_invalid", "运行验收目录无效，请检查本机数据目录。"
            )
        with FileLock(lock, timeout=0, mode=0o600):
            upgrade = False
            try:
                settings.require_qualified()
                return settings, False
            except QualificationUpgradeRequired:
                upgrade = True
            except RuntimePolicyError:
                pass  # Only the real runner may produce the missing qualification.
            previous = _read_setup_attempt(attempt, qualification)
            if (
                previous
                and not retry
                and previous.get("model_attempted") is not False
                and not _attempt_binding_changed(previous, settings)
                and not (
                    upgrade
                    and previous.get("state") == "passed"
                    and previous.get("route_identity") == route.identity
                )
            ):
                raise _qualification_failure(previous, retry_hint=retry_hint)
            # Write before any model call, including process interruption or crash.
            binding = {
                "route_identity": route.identity,
                "host_identity": qualification_host_identity(),
            }
            _write_private(attempt, json.dumps({"state": "started", **binding}))
            from app.infrastructure.chat_stream_lifetime import publish_stream_note

            publish_stream_note(
                "正在验收已配置的模型与本机执行器，首次验收可能需要数分钟；通过后继续处理本轮请求。"
            )
            result = qualify_runtime(settings, owner_scope=owner_scope, upstream_evidence=evidence)
            if result.get("ok") is True:
                try:
                    settings.require_qualified()
                except RuntimePolicyError:
                    result = {
                        **result,
                        "ok": False,
                        "error_code": "runtime_qualification_evidence_missing",
                    }
            failure = _qualification_failure(result, retry_hint=retry_hint)
            _write_private(
                attempt,
                json.dumps(
                    {
                        "state": "passed" if result.get("ok") else "failed",
                        **binding,
                        "error_code": failure.code if result.get("ok") is not True else None,
                        "checks": failure.checks,
                        "model_attempted": result.get("model_attempted") is not False,
                    }
                ),
            )
            if result.get("ok") is not True:
                raise failure
            return settings, True
    except Timeout as exc:
        raise RuntimeSetupError(
            "runtime_qualification_in_progress", "当前模型正在完成运行验收，请稍后继续。"
        ) from exc
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "运行验收状态无法安全保存，请检查本机数据目录权限。"
        ) from exc


def _deployment_runtime_settings(*, retry: bool = False) -> RuntimeSettings:
    """Local operator entry only; never resolves an account or starts a business task."""
    settings = runtime_settings()
    route, root, destination = settings.route, settings.runtime_root, settings.qualification_file
    if route is None or root is None or destination is None:
        raise RuntimeSetupError(
            "runtime_configuration_required",
            "请先设置有效的 XCAGI_AGENT_RUNTIME_CONFIG；本机部署验收不会改用账号默认模型。",
        )
    if (
        not root.is_absolute()
        or root.parent == root
        or not destination.is_absolute()
        or not destination.is_relative_to(root)
        or not destination.relative_to(root).parts
        or ".." in destination.relative_to(root).parts
        or destination.exists()
        and not destination.is_file()
        or any(
            path.is_symlink() or (path != destination and path.exists() and not path.is_dir())
            for path in (root, destination, *destination.parents)
            if path.is_relative_to(root)
        )
        or not destination.resolve().is_relative_to(root.resolve())
    ):
        raise RuntimeSetupError(
            "runtime_storage_invalid",
            "部署资格文件必须位于私有运行目录内，且不能通过符号链接访问。",
        )
    _validate_storage(settings)
    # Validate credentials and paths before any lock/attempt creation. Existing
    # deployment roots are verified, never chmod'ed (they may be shared /tmp).
    route.token()
    root, destination = root.resolve(), destination.resolve()
    if root.exists() and (
        not root.is_dir()
        or os.name == "posix"
        and (root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077)
    ):
        raise RuntimeSetupError(
            "runtime_storage_invalid", "部署运行目录必须由当前用户拥有且仅该用户可访问。"
        )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = replace(settings, runtime_root=root, qualification_file=destination)
    _qualified_settings(
        settings,
        owner_scope="deployment:" + hashlib.sha256(str(root).encode()).hexdigest(),
        evidence={},
        retry=retry,
        retry_hint="修复后请在部署主机执行 xcagi-brain --json runtime-check --deployment --retry。",
    )
    current = runtime_settings()
    if current.runtime_root is not None and current.qualification_file is not None:
        current = replace(
            current,
            runtime_root=current.runtime_root.resolve(),
            qualification_file=current.qualification_file.resolve(),
        )
    if current != settings:
        raise RuntimeSetupError(
            "runtime_changed", "验收期间部署模型或运行目录已变化；请恢复原配置后重新检查。"
        )
    current.require_qualified().token()
    return current


def get_deployment_runtime_settings(*, retry: bool = False) -> RuntimeSettings:
    try:
        return _deployment_runtime_settings(retry=retry)
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "部署运行目录无法安全访问，请检查本机数据目录权限。"
        ) from exc


def _prepared_route(connection: Connection, selected: tuple[str, str] | None) -> PreparedChatRoute:
    # The route read is a plain GET with no model usage, so a connection-level
    # failure means nothing was sent or spent; retry a transient DNS/proxy miss
    # instead of failing the whole turn once.
    for attempt in range(_ROUTE_READ_ATTEMPTS):
        try:
            snapshot = resolve_account_route(
                connection, httpx_sync_client, selected, runtime="codex"
            )
            break
        except MarketModelError as exc:
            message = {
                "CODEX_MODEL_UNSUPPORTED": "当前模型地址或密钥协议不支持独立运行，请在已有模型设置中核对模型服务。",
                "CODEX_MODEL_METADATA_REQUIRED": "当前模型缺少已确认的独立上游厂商和真实模型标识，请在模型设置中核对。",
                "CODEX_MODEL_CAPACITY_REQUIRED": "当前模型缺少有效的上下文容量和最大输出量，请在模型设置中补全。",
                "CODEX_ROUTE_SIGNING_UNAVAILABLE": "平台暂时无法签发当前账号的模型路由，请联系管理员检查模型网关配置。",
                "XIAOX_ROUTE_SIGNING_UNAVAILABLE": "平台暂时无法签发当前账号的模型路由，请联系管理员检查模型网关配置。",
            }.get(exc.code or "", "平台模型配置暂时不可用，请检查账号连接和已保存的模型设置。")
            raise RuntimeSetupError("runtime_configuration_required", message) from exc
        except httpx.RequestError as exc:
            if attempt + 1 >= _ROUTE_READ_ATTEMPTS:
                raise RuntimeSetupError(
                    "runtime_platform_unavailable", "平台模型配置暂时无法读取，请检查网络后重试。"
                ) from exc
            time.sleep(0.4 * (attempt + 1))
    return PreparedChatRoute(connection, (snapshot["provider"], snapshot["model"]), snapshot)


def _turn_timeout_seconds() -> int:
    """单轮预算；默认 300 秒，可通过环境变量放宽但不得超过对话总预算。"""
    raw = os.environ.get("XCAGI_RUNTIME_TURN_TIMEOUT_SEC", "300").strip()
    try:
        value = int(float(raw))
    except ValueError:
        value = 300
    return max(60, min(value, 570))


def _account_runtime_inputs(
    owner: str, previous: dict[str, Any] | None = None
) -> tuple[RuntimeSettings, str, PreparedChatRoute]:
    """Resolve the authoritative account route without writing local state."""
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
    try:
        host = qualification_host_identity()
    except RuntimePolicyError as exc:
        raise RuntimeSetupError(
            "runtime_host_unverified", "本机版本身份无法核验，请检查安装包或部署版本记录。"
        ) from exc
    host_key = hashlib.sha256(json.dumps(host, sort_keys=True).encode()).hexdigest()
    try:
        state = Path(get_desktop_state_dir(create=False)).expanduser().resolve()
        # Keep the legacy on-disk namespace for new and upgraded accounts.
        # Existing Xiaox-only state must also remain in place: moving it would
        # invalidate absolute evidence references and risk duplicate paid calls.
        legacy, renamed = (state / name / scope for name in ("codex-runtime", "xiaox-runtime"))
        for candidate in (legacy, renamed):
            for directory in (candidate.parent, candidate):
                if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                    raise RuntimeSetupError(
                        "runtime_storage_invalid", "运行状态目录无效，请检查本机数据目录。"
                    )
        if legacy.exists() and renamed.exists():
            raise RuntimeSetupError(
                "runtime_storage_invalid",
                "同一账号存在两套运行状态，请先核对任务与计费回执；不会自动合并或重新执行。",
            )
        root = renamed if renamed.exists() else legacy
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "本机运行状态目录无法读取，请检查数据目录权限。"
        ) from exc
    evidence_root = root / "qualifications" / route.identity / host_key
    settings = RuntimeSettings(
        route=route,
        runtime_root=root,
        qualification_file=evidence_root / "qualification.json",
        turn_timeout_seconds=_turn_timeout_seconds(),
    )
    return settings, scope, prepared


def get_account_runtime_settings(
    owner: str,
    *,
    previous: dict[str, Any] | None = None,
    retry: bool = False,
    qualify: bool = True,
) -> RuntimeSettings:
    """Called only after the gateway verifies the actor and any existing task owner."""
    settings, scope, prepared = _account_runtime_inputs(owner, previous)
    root, destination, route = settings.runtime_root, settings.qualification_file, settings.route
    assert root is not None and destination is not None and route is not None
    _private_directory(root.parent)
    _validate_storage(settings, create=True)
    if not qualify:
        return settings  # Staging freezes the route without paid model calls.
    settings, fresh = _qualified_settings(
        settings, owner_scope=scope, evidence=prepared.snapshot["runtime"], retry=retry
    )
    if fresh:
        # Qualification can consume most of the short-lived route-token TTL.
        # Refresh the same snapshot before business execution, never the default.
        refreshed = _model_route(_prepared_route(prepared.connection, prepared.route))
        if refreshed.identity != route.identity:
            raise RuntimeSetupError(
                "runtime_changed",
                "验收期间模型配置已变化，请重新读取模型设置；本轮未启动业务执行。",
            )
        settings = replace(settings, route=refreshed)
    return settings


def _read_setup_attempt(path: Path, qualification: Path) -> dict:
    if not path.exists() and not qualification.exists():
        try:
            with os.scandir(path.parent) as entries:
                if not any(entry.name.startswith("attempt-") for entry in entries):
                    return {}
        except FileNotFoundError:
            return {}
    try:
        with path.open(encoding="utf-8") as stream:
            result = json.loads(stream.read(65_537))
        if isinstance(result, dict) and result.get("state") in {"passed", "failed"}:
            return result
    except (OSError, ValueError):
        pass
    # A missing journal beside prior probe evidence, truncation or a crash cannot
    # prove that no paid request was sent. A valid current certificate is reused first.
    return {"state": "interrupted", "error_code": "runtime_qualification_interrupted"}


def _attempt_binding_changed(attempt: dict, settings: RuntimeSettings) -> bool:
    # An unidentified/interrupted legacy attempt is never proof that a retry is safe.
    previous_host, previous_route = attempt.get("host_identity"), attempt.get("route_identity")
    return bool(
        isinstance(previous_host, dict)
        and set(previous_host) == {"git_sha", "system", "machine"}
        and isinstance(previous_host.get("git_sha"), str)
        and re.fullmatch(r"[0-9a-f]{40}", previous_host["git_sha"])
        and all(
            isinstance(previous_host.get(key), str) and previous_host[key].strip()
            for key in ("system", "machine")
        )
        and isinstance(previous_route, str)
        and re.fullmatch(r"[0-9a-f]{64}", previous_route)
        and attempt.get("state") in {"passed", "failed"}
        and settings.route is not None
        and (
            previous_route != settings.route.identity
            or previous_host != qualification_host_identity()
        )
    )


def _validate_storage(settings: RuntimeSettings, *, create: bool = False) -> None:
    root, destination = settings.runtime_root, settings.qualification_file
    if root is None or not root.is_absolute():
        raise RuntimeSetupError(
            "runtime_configuration_required", "本机运行配置缺少有效的私有状态目录。"
        )
    paths = [root.parent, root]
    if destination is not None:
        try:
            relative = destination.parent.relative_to(root)
            if not destination.is_absolute() or ".." in relative.parts:
                raise ValueError("invalid qualification location")
        except ValueError as exc:
            raise RuntimeSetupError(
                "runtime_storage_invalid", "运行验收文件必须位于本机私有状态目录内。"
            ) from exc
        paths.extend(root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1))
    try:
        for path in paths:
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise RuntimeSetupError(
                    "runtime_storage_invalid", "运行验收目录无效，请检查本机数据目录。"
                )
            if create and path != root.parent:
                _private_directory(path)
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "运行验收目录无法访问，请检查本机数据目录权限。"
        ) from exc


def _runtime_qualification_status(settings: RuntimeSettings) -> dict[str, Any]:
    """Read original evidence and its lock; never run the model or produce a receipt."""
    _validate_storage(settings)
    if settings.route is not None:
        settings.route.token()
    status: dict[str, Any] = {
        "success": True,
        "runtime": "xiaox",
        "codex_version": CODEX_VERSION,
        "qualification": "required",
        "route": settings.route.runtime_identity() if settings.route else {},
        "checks": {},
        "error_code": "runtime_qualification_required",
        "message": _QUALIFICATION_ERRORS["runtime_qualification_required"],
        "retry_required": False,
    }
    qualification = settings.qualification_file
    if qualification is None:
        return status
    attempt, lock = (
        qualification.with_name("setup-attempt.json"),
        qualification.with_name("setup.lock"),
    )
    if any(path.is_symlink() for path in (qualification, attempt, lock)):
        raise RuntimeSetupError("runtime_storage_invalid", "运行验收目录无效，请检查本机数据目录。")

    def read() -> dict[str, Any]:
        try:
            settings.require_qualified()
        except RuntimePolicyError as exc:
            previous = _read_setup_attempt(attempt, qualification)
            if _attempt_binding_changed(previous, settings) or (
                isinstance(exc, QualificationUpgradeRequired)
                and previous.get("state") == "passed"
                and settings.route is not None
                and previous.get("route_identity") == settings.route.identity
            ):
                return status
            if previous:
                failure = _qualification_failure(previous)
                state = "interrupted" if previous.get("state") == "interrupted" else "failed"
                status.update(
                    qualification="required" if previous.get("model_attempted") is False else state,
                    error_code=failure.code,
                    message=str(failure),
                    checks=failure.checks,
                    retry_required=previous.get("model_attempted") is not False,
                )
            return status
        status.update(
            qualification="passed",
            error_code=None,
            message="当前账号与本机版本的运行验收已通过。",
            checks=dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
        )
        return status

    if not lock.exists():
        return read()
    try:
        with FileLock(lock, timeout=0, mode=0o600):
            return read()
    except Timeout:
        status.update(
            qualification="in_progress",
            error_code="runtime_qualification_in_progress",
            message="当前账号的模型正在完成运行验收，请稍后继续。",
        )
        return status


def runtime_qualification_status(settings: RuntimeSettings) -> dict[str, Any]:
    try:
        return _runtime_qualification_status(settings)
    except OSError as exc:
        raise RuntimeSetupError(
            "runtime_storage_invalid", "运行验收状态无法读取，请检查本机数据目录权限。"
        ) from exc


def get_account_runtime_status(owner: str) -> dict[str, Any]:
    settings, _scope, _prepared = _account_runtime_inputs(owner)
    return runtime_qualification_status(settings)
