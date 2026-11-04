"""Typed operation ports shared by mobile components; no composition-root lookup."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Any, ParamSpec, Protocol, TypeVar, runtime_checkable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.application.ai_group_chat_service import AiGroupChatService
    from app.application.facades.mobile_relay_facade import MobileRelayService
    from app.application.im_app_service import ImApplicationService
    from app.db.xcmax_sync import SyncDb
    from app.fastapi_routes.mod_store.schemas import ModStoreInstallResult
    from app.infrastructure.mods.mod_manager import ModManager


class MobilePrincipal(Protocol):
    @property
    def id(self) -> int: ...


UserDependency = Callable[..., Awaitable[MobilePrincipal | None]]

_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def late_callback(
    resolve: Callable[[], Callable[_Params, _Result]],
) -> Callable[_Params, _Result]:
    """Resolve one explicit collaborator per call, preserving omitted/keyword args."""

    def call(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        return resolve()(*args, **kwargs)

    return call


class SuperEmployeePort(Protocol):
    def list_messages(self, *, user_id: int, limit: int) -> list[dict[str, Any]]: ...
    def invoke(self, *, user_id: int, message: str, context: dict[str, Any]) -> dict[str, Any]: ...
    def invoke_stream(
        self, *, user_id: int, message: str, context: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]: ...


class AiGroupChatServiceFactory(Protocol):
    def __call__(self, *, mode: str) -> AiGroupChatService: ...


class ClaudeSuperEmployeeServiceFactory(Protocol):
    def __call__(self) -> SuperEmployeePort: ...


class CodexSuperEmployeeServiceFactory(Protocol):
    def __call__(self) -> SuperEmployeePort: ...


class CursorSuperEmployeeServiceFactory(Protocol):
    def __call__(self) -> SuperEmployeePort: ...


class MobileRelayServiceFactory(Protocol):
    def __call__(self) -> MobileRelayService: ...


class TraeSuperEmployeeServiceFactory(Protocol):
    def __call__(self) -> SuperEmployeePort: ...


class AdminDutyModItemCall(Protocol):
    def __call__(
        self,
        market_profiles: dict[str, dict[str, Any]] | None = None,
        *,
        market_connected: bool = False,
    ) -> dict[str, Any] | None: ...


class AdminDutyRecordsFromRosterCall(Protocol):
    def __call__(self) -> list[dict[str, Any]]: ...


class AdminEmployeeItemsCall(Protocol):
    def __call__(
        self,
        market_profiles: dict[str, dict[str, Any]] | None = None,
        *,
        market_connected: bool = False,
        im_summary: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]: ...


class AdminEmployeeManifestCall(Protocol):
    def __call__(self, employee_id: str) -> dict[str, Any]: ...


class AdminEmployeeMatchKeysCall(Protocol):
    def __call__(self, raw: dict[str, Any], employee_id: str, name: str) -> list[str]: ...


class AdminRosterAreaLabelsCall(Protocol):
    def __call__(self) -> dict[str, str]: ...


class AdminRosterIdsByDepartmentOrderCall(Protocol):
    def __call__(self) -> list[str]: ...


class AiCircleEmployeeProfilesCall(Protocol):
    def __call__(self) -> dict[str, dict[str, str]]: ...


class AiCircleUserCall(Protocol):
    def __call__(self, user: object) -> tuple[int, str, str | None]: ...


class AiConversationChangesCall(Protocol):
    def __call__(self, user: object, limit: int = 100) -> list[dict[str, Any]]: ...


class ApplyMarketProfileCall(Protocol):
    def __call__(
        self, item: dict[str, Any], profile: dict[str, Any] | None, *, market_connected: bool
    ) -> None: ...


class ApprovalItemsCall(Protocol):
    def __call__(self, limit: int = 100) -> list[dict[str, Any]]: ...


class CachedDesktopRelayForAccountBindingCall(Protocol):
    def __call__(self) -> dict[str, Any] | None: ...


class ChunkEmployeeReplyCall(Protocol):
    def __call__(self, text: str) -> list[str]: ...


class CompactTextCall(Protocol):
    def __call__(self, value: Any) -> str: ...


class EmployeeSsotPayloadCall(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class EnrichPairingPayloadCall(Protocol):
    def __call__(
        self, payload: dict[str, Any], request: Request | None = None
    ) -> dict[str, Any]: ...


class EnrichWorkflowEmployeesCall(Protocol):
    def __call__(
        self,
        mod_id: str,
        employees: list[Any],
        market_profiles: dict[str, dict[str, Any]] | None = None,
        *,
        market_connected: bool = False,
    ) -> list[dict[str, Any]]: ...


class EnsureMobileDeviceTableCall(Protocol):
    def __call__(self) -> None: ...


class EnsureOutboxTableCall(Protocol):
    def __call__(self) -> None: ...


class ExtractEmployeeFailureTextCall(Protocol):
    def __call__(self, result: dict) -> str: ...


class ExtractEmployeeReplyTextCall(Protocol):
    def __call__(self, result: dict) -> str: ...


class GuessLanIpv4Call(Protocol):
    def __call__(self) -> str: ...


class HostIsPrivateOrLoopbackCall(Protocol):
    def __call__(self, host: str) -> bool: ...


class LoadAdminDutyRecordsCall(Protocol):
    def __call__(self) -> list[dict[str, Any]]: ...


class LoadMarketAiEmployeeProfileIndexCall(Protocol):
    async def __call__(self) -> tuple[dict[str, dict[str, Any]], bool, str]: ...


class MobileBridgeRequestStatusesCall(Protocol):
    def __call__(self) -> tuple[str, ...]: ...


class MobileCheckoutSignBodyCall(Protocol):
    def __call__(self, body: dict[str, Any]) -> dict[str, Any]: ...


class MobileCsSourceIdCall(Protocol):
    def __call__(self, user: object) -> str: ...


class MobileCsSourceNameCall(Protocol):
    def __call__(self, user: object) -> str: ...


class MobileGroupModeCall(Protocol):
    def __call__(self, request: Request) -> str: ...


class MobileGroupUidCall(Protocol):
    def __call__(self, request: Request, user: object) -> int: ...


class MobileMarketAuthorizationCall(Protocol):
    def __call__(self, request: Request, user: object = None) -> str: ...


class MobileModItemsCall(Protocol):
    def __call__(
        self,
        market_profiles: dict[str, dict[str, Any]] | None = None,
        *,
        market_connected: bool = False,
    ) -> list[dict[str, Any]]: ...


class MobileRequestUserIdCall(Protocol):
    def __call__(self, request: Request, user: object) -> int: ...


class MobileSessionIdFromRequestCall(Protocol):
    def __call__(self, request: Request) -> str: ...


class MobileSessionMetaCall(Protocol):
    def __call__(self, request: Request) -> dict[str, Any]: ...


class MobileSyncCirclePostsCall(Protocol):
    async def __call__(self, user: object, *, limit: int = 50) -> list[dict[str, Any]]: ...


class MobileSyncRuntimeContractCall(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class MobileUnauthorizedResponseCall(Protocol):
    def __call__(self) -> JSONResponse: ...


class MobileUserIdentityCall(Protocol):
    def __call__(self, user: object) -> tuple[int, str]: ...


class MobileUserPublicDictCall(Protocol):
    def __call__(self, user: object) -> dict[str, Any]: ...


class ModstoreAdminProxyCall(Protocol):
    async def __call__(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]: ...


class ModstoreAdminTokenCall(Protocol):
    def __call__(self) -> str: ...


class ModstorePlatformBaseCall(Protocol):
    def __call__(self) -> str: ...


class NormalizeMobilePaymentChannelCall(Protocol):
    def __call__(self, raw: Any) -> str: ...


class PairingIssueHostCall(Protocol):
    def __call__(self, requested: str) -> str: ...


class PairingIssuePortCall(Protocol):
    def __call__(self, request: Request, requested: int) -> int: ...


class PairingRateAllowedCall(Protocol):
    def __call__(self, key: str, endpoint: str, limit: int, window: int) -> bool: ...


class PairingReachablePortCall(Protocol):
    def __call__(self, request: Request | None, api_port: int) -> int: ...


class RegisterDesktopRelayForPairingCall(Protocol):
    def __call__(self, host: str, port: int) -> dict[str, Any] | None: ...


class RelayMobileAuthPayloadCall(Protocol):
    def __call__(
        self, user_public: dict[str, Any], desktop: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class RequireMobileAdminCall(Protocol):
    def __call__(
        self, request: Request, user: object
    ) -> tuple[dict[str, Any], JSONResponse | None]: ...


class RequireMobileAdminOrEnterpriseCall(Protocol):
    def __call__(
        self, request: Request, user: object
    ) -> tuple[dict[str, Any], JSONResponse | None]: ...


class SafeMobileSyncItemsCall(Protocol):
    def __call__(
        self, name: str, loader: Callable[[], list[dict[str, Any]]]
    ) -> list[dict[str, Any]]: ...


class SafeUserIdCall(Protocol):
    def __call__(self, user: object) -> int: ...


class SafeUserTextCall(Protocol):
    def __call__(self, user: object, key: str) -> str: ...


class ShipmentItemsCall(Protocol):
    def __call__(self, limit: int = 100) -> list[dict[str, Any]]: ...


class SseLineCall(Protocol):
    def __call__(self, payload: dict) -> bytes: ...


class StreamSuperEmployeeInvokeCall(Protocol):
    async def __call__(
        self, request: Request, tool: str, body: dict[str, Any], user: object
    ) -> Response: ...


class SuperEmployeeServiceForToolCall(Protocol):
    def __call__(self, tool: str) -> SuperEmployeePort | None: ...


class TrustedDesktopPairingRequestCall(Protocol):
    def __call__(self, request: Request) -> bool: ...


class UpsertAdminDutyModItemCall(Protocol):
    def __call__(
        self,
        items: list[dict[str, Any]],
        market_profiles: dict[str, dict[str, Any]] | None = None,
        *,
        market_connected: bool = False,
    ) -> None: ...


class AddCommentCall(Protocol):
    def __call__(self, *, post_id: int, user_id: int, author_name: str, body: str) -> int: ...


class ApplyInboxCall(Protocol):
    def __call__(self, *, limit: int) -> dict[str, Any]: ...


class AuthHeaderCall(Protocol):
    def __call__(self, token: str) -> str: ...


class CachedRelayCall(Protocol):
    def __call__(self) -> dict[str, Any] | None: ...


class ConsumeByShortcodeCall(Protocol):
    def __call__(self, code: str) -> dict[str, Any] | None: ...


class ConsumePairingNonceCall(Protocol):
    def __call__(self, nonce: str) -> dict[str, Any] | None: ...


class CreatePostCall(Protocol):
    def __call__(self, *, user_id: int, author_name: str, avatar: str | None, body: str) -> int: ...


class DatabaseCall(Protocol):
    def __call__(self) -> AbstractContextManager[Session]: ...


class DutyRosterCall(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class EmployeeSsotCall(Protocol):
    def __call__(self, *, installed_ids: set[str]) -> dict[str, Any]: ...


class EnsureSyncSchemaCall(Protocol):
    def __call__(self, conn: sqlite3.Connection) -> None: ...


class ExecuteEmployeeCall(Protocol):
    def __call__(
        self,
        employee_id: str,
        task: str,
        input_data: dict[str, Any],
        *,
        user_id: int,
        workspace_root: str | None,
        session_id: str | None,
    ) -> dict[str, Any]: ...


class FactoryContextCall(Protocol):
    def __call__(
        self, workspace_id: str = "xcmax", base: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class FixedContactsCall(Protocol):
    def __call__(self, surface: str) -> dict[str, Any]: ...


class GrantEntitlementsCall(Protocol):
    async def __call__(self, session_id: str, industry_id: str) -> dict[str, Any]: ...


class ImServiceCall(Protocol):
    def __call__(self, db: Session) -> ImApplicationService: ...


class IndustryCatalogCall(Protocol):
    async def __call__(self, request: Request) -> dict[str, Any]: ...


class IndustryPlanCall(Protocol):
    async def __call__(self, request: Request, industry_id: str) -> dict[str, Any]: ...


class InstallCustomerSeedCall(Protocol):
    async def __call__(
        self,
        *,
        request: Request,
        mod_id: str,
        industry_id: str,
        market_token: str,
        account_username: str,
    ) -> dict[str, Any]: ...


class InstallFoundationCall(Protocol):
    async def __call__(self, edition: str | None) -> ModStoreInstallResult: ...


class InstallIndustrySeedCall(Protocol):
    async def __call__(self, industry_id: str) -> dict[str, Any]: ...


class InstallModCall(Protocol):
    async def __call__(
        self, pkg_id: str, version: str, activate: bool = True
    ) -> ModStoreInstallResult: ...


class InstalledEmployeeIdsCall(Protocol):
    def __call__(self) -> set[str]: ...


class IsDesktopCall(Protocol):
    def __call__(self) -> bool: ...


class IssuePairingNonceCall(Protocol):
    def __call__(self, host: str, port: int, ttl_seconds: int = 300) -> dict[str, Any]: ...


class LatestMarketTokenCall(Protocol):
    def __call__(self, *, user_id: int | None = None) -> str: ...


class ListPostsCall(Protocol):
    def __call__(self, *, user_id: int, limit: int = 50) -> list[dict[str, Any]]: ...


class LookupByShortcodeCall(Protocol):
    def __call__(self, code: str) -> dict[str, Any] | None: ...


class MarketBaseUrlCall(Protocol):
    def __call__(self) -> str: ...


class MarketProxyCall(Protocol):
    async def __call__(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        authorization: str = "",
        return_error_payload: bool = False,
    ) -> object: ...


class ModManagerCall(Protocol):
    def __call__(self) -> ModManager: ...


class NowCall(Protocol):
    def __call__(self) -> datetime: ...


class PlatformShellCall(Protocol):
    def __call__(self, installed_mod_ids: list[str]) -> dict[str, Any]: ...


class ProcessCsMessageCall(Protocol):
    async def __call__(
        self, conversation_id: int, customer_user_id: int, message_id: int, body: str
    ) -> None: ...


class RegisterRelayCall(Protocol):
    def __call__(self, *, host: str, port: int) -> dict[str, Any]: ...


class RequestSessionIdCall(Protocol):
    def __call__(self, request: Request) -> str: ...


class ResolveMarketTokenCall(Protocol):
    async def __call__(self, session_id: str) -> str: ...


class RosterDocumentCall(Protocol):
    def __call__(self) -> dict[str, Any]: ...


class SelectIndustryCall(Protocol):
    def __call__(
        self, user: object, industry_id: str, *, industry_mod_id: str = ""
    ) -> dict[str, Any]: ...


class SessionFactoryCall(Protocol):
    def __call__(self) -> Session: ...


class SessionMarketTokenCall(Protocol):
    def __call__(self, sid: str) -> str: ...


class SetAccountIndustryCall(Protocol):
    def __call__(self, username: str, industry_id: str) -> None: ...


class SyncCircleCall(Protocol):
    async def __call__(self) -> object: ...


class SyncConnectionCall(Protocol):
    def __call__(self) -> AbstractContextManager[sqlite3.Connection]: ...


class SyncDatabaseCall(Protocol):
    def __call__(self) -> SyncDb: ...


class ToggleLikeCall(Protocol):
    def __call__(self, *, post_id: int, user_id: int) -> bool: ...


class VerifyJwtCall(Protocol):
    def __call__(self, token: str) -> dict[str, Any] | None: ...


@runtime_checkable
class ClosableEventStream(Protocol):
    async def aclose(self) -> None: ...
