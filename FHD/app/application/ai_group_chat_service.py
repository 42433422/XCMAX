"""AI group chat public API and explicit application component assembly."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.application.group_chat.catalog import GroupCatalog
from app.application.group_chat.constants import (
    _LEGACY_SUPER_EMPLOYEE_IDS as _LEGACY_SUPER_EMPLOYEE_IDS,
)
from app.application.group_chat.constants import _SUPER_EMPLOYEE_IDS as _SUPER_EMPLOYEE_IDS
from app.application.group_chat.constants import (
    _SUPER_EMPLOYEE_RELAY_KINDS as _SUPER_EMPLOYEE_RELAY_KINDS,
)
from app.application.group_chat.constants import _XIAOC_ASSISTANT_ID as _XIAOC_ASSISTANT_ID
from app.application.group_chat.constants import (
    CHAT_ACCEPTANCE_SUMMARY_CHARS as CHAT_ACCEPTANCE_SUMMARY_CHARS,
)
from app.application.group_chat.constants import (
    CHAT_REPORT_SUMMARY_CHARS as CHAT_REPORT_SUMMARY_CHARS,
)
from app.application.group_chat.constants import CONTEXT_TURNS as CONTEXT_TURNS
from app.application.group_chat.constants import MAX_RESPONDERS as MAX_RESPONDERS
from app.application.group_chat.constants import (
    PUBLIC_ACCEPTANCE_BODY_MAX_CHARS as PUBLIC_ACCEPTANCE_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    PUBLIC_CHAT_BODY_MAX_CHARS as PUBLIC_CHAT_BODY_MAX_CHARS,
)
from app.application.group_chat.constants import (
    RELAY_PROGRESS_MIN_INTERVAL_SEC as RELAY_PROGRESS_MIN_INTERVAL_SEC,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC as SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_DEFAULT_ROUNDS as SUPER_DISCUSSION_DEFAULT_ROUNDS,
)
from app.application.group_chat.constants import (
    SUPER_DISCUSSION_MAX_ROUNDS as SUPER_DISCUSSION_MAX_ROUNDS,
)
from app.application.group_chat.constants import CompletionFn as CompletionFn
from app.application.group_chat.constants import EmployeeExecutorFn as EmployeeExecutorFn
from app.application.group_chat.constants import _env_float as _env_float
from app.application.group_chat.conversation import GroupConversation
from app.application.group_chat.directory import GroupDirectory
from app.application.group_chat.discussion_router import GroupDiscussion
from app.application.group_chat.dispatch_targeting import DispatchTargeting
from app.application.group_chat.employee_execution import EmployeeExecution
from app.application.group_chat.employee_registry import (
    _FALLBACK_DEPARTMENTS as _FALLBACK_DEPARTMENTS,
)
from app.application.group_chat.employee_registry import (
    _FALLBACK_ENTERPRISE_DEPARTMENTS as _FALLBACK_ENTERPRISE_DEPARTMENTS,
)
from app.application.group_chat.employee_registry import (
    _append_super_employees as _append_super_employees,
)
from app.application.group_chat.employee_registry import _default_completion as _default_completion
from app.application.group_chat.employee_registry import (
    _default_departments as _default_departments,
)
from app.application.group_chat.employee_registry import (
    _default_duty_employee_loader as _default_duty_employee_loader,
)
from app.application.group_chat.employee_registry import (
    _default_employee_executor as _default_employee_executor,
)
from app.application.group_chat.employee_registry import (
    _default_enterprise_departments as _default_enterprise_departments,
)
from app.application.group_chat.employee_registry import (
    _default_enterprise_employee_loader as _default_enterprise_employee_loader,
)
from app.application.group_chat.employee_registry import (
    _dept_key_to_employee_ids as _dept_key_to_employee_ids,
)
from app.application.group_chat.employee_registry import _employee_manifest as _employee_manifest
from app.application.group_chat.employee_registry import (
    _is_required_group_member as _is_required_group_member,
)
from app.application.group_chat.employee_registry import _member_employee_id as _member_employee_id
from app.application.group_chat.employee_registry import (
    _member_public_shape as _member_public_shape,
)
from app.application.group_chat.employee_registry import (
    _normalize_branch_context as _normalize_branch_context,
)
from app.application.group_chat.employee_registry import _safe_json_line as _safe_json_line
from app.application.group_chat.employee_registry import _utc_now as _utc_now
from app.application.group_chat.employee_registry import (
    _with_required_group_members as _with_required_group_members,
)
from app.application.group_chat.employee_registry import (
    _xiaoc_assistant_member as _xiaoc_assistant_member,
)
from app.application.group_chat.employee_transport import EmployeeTransport
from app.application.group_chat.evidence import ExecutionResultPolicy
from app.application.group_chat.message_formatting import ChatFormatting
from app.application.group_chat.ports import (
    ConversationActions,
    DirectoryActions,
    EmployeeProviders,
    GroupStore,
    MessageFactory,
    MessageStore,
    MobileRelay,
    ProgressSources,
    SuperEmployee,
)
from app.application.group_chat.progress import ProgressSync
from app.application.group_chat.projections import ChatProjection
from app.application.group_chat.replies import ChatReplies
from app.application.group_chat.storage import GroupChatRepository
from app.application.group_chat.work_dispatch import WorkDispatch
from app.application.group_chat.work_reports import WorkReports
from app.utils.path_io.path_utils import get_app_data_dir


class AiGroupChatService:
    """User-isolated group chat assembled from explicit application components."""

    def __init__(
        self,
        storage_root: str | Path | None = None,
        completion_fn: CompletionFn | None = None,
        employee_executor_fn: EmployeeExecutorFn | None = None,
        department_loader: Callable[[], dict[str, Any]] | None = None,
        employee_loader: Callable[[], list[dict[str, Any]]] | None = None,
        mode: str = "admin",
    ) -> None:
        self._mode = mode if mode in {"admin", "enterprise"} else "admin"
        self._completion_fn = completion_fn or _default_completion
        self._employee_executor_fn = employee_executor_fn or _default_employee_executor
        self._has_custom_employee_executor = employee_executor_fn is not None
        self._department_loader = (
            department_loader
            if department_loader is not None
            else _default_enterprise_departments
            if self._mode == "enterprise"
            else _default_departments
        )
        self._employee_loader = (
            employee_loader
            if employee_loader is not None
            else _default_enterprise_employee_loader
            if self._mode == "enterprise"
            else _default_duty_employee_loader
        )
        self._storage = GroupChatRepository(
            Path(storage_root) if storage_root is not None else Path(get_app_data_dir())
        )
        self._root = self._storage.root
        self._groups_path = self._storage._groups_path
        self._messages_path = self._storage._messages_path
        groups = GroupStore(
            lambda: self._all_groups(),
            lambda uid: self._user_groups(uid),
            lambda row: self._append_group(row),
            lambda rows: self._rewrite_groups(rows),
            lambda **kw: self._resolve_group_id(**kw),
            lambda: self._compact_groups_file_if_needed(),
        )
        messages = MessageStore(
            lambda: self._read_messages(),
            lambda rows: self._append_messages(rows),
            lambda rows: self._rewrite_messages(rows),
            lambda uid: self._latest_previews(uid),
        )
        providers = EmployeeProviders(
            lambda: self._mobile_relay_service(),
            lambda employee_id: self._super_employee_service(employee_id),
        )
        progress_sources = ProgressSources(
            lambda **kw: self._sync_relay_progress_for_group(**kw),
            lambda **kw: self._sync_super_employee_progress_for_group(**kw),
        )
        make_row: MessageFactory = lambda **kw: self._message_row(**kw)
        self._directory = GroupDirectory(
            groups,
            mode=self._mode,
            load_employees=lambda: self._employee_loader(),
            load_departments=lambda: self._department_loader(),
        )
        self._catalog = GroupCatalog(
            groups,
            messages,
            DirectoryActions(
                lambda uid: self._seed_department_groups(uid),
                lambda rows: self._backfill_department_members(rows),
            ),
            mode=self._mode,
        )
        self._targeting = DispatchTargeting(self._mode)
        self._employee_transport = EmployeeTransport(
            providers, lambda **kw: self._create_super_employee_relay_task(**kw)
        )
        self._employee_execution = EmployeeExecution(
            execute=lambda employee_id, task, data, uid: self._employee_executor_fn(
                employee_id, task, data, uid
            ),
            has_custom_executor=lambda: self._has_custom_employee_executor,
            invoke_super=lambda **kw: self._invoke_super_employee_task(**kw),
        )
        self._replies = ChatReplies(
            complete=lambda messages: self._completion_fn(messages),
            providers=providers,
            super_reply=lambda group, member, history, **kw: self._super_employee_reply(
                group, member, history, **kw
            ),
        )
        self._progress = ProgressSync(
            messages, providers, lambda **kw: self.append_relay_work_report(**kw), make_row
        )
        self._work_reports = WorkReports(groups, messages, progress_sources, make_row)
        self._work_dispatch = WorkDispatch(
            messages, lambda **kw: self._execute_employee_work(**kw), make_row
        )
        self._discussion_router = GroupDiscussion(
            messages,
            make_row,
            complete=lambda messages: self._completion_fn(messages),
            timeout=lambda: SUPER_DISCUSSION_COMPLETION_TIMEOUT_SEC,
            reply=lambda **kw: self._super_discussion_reply(**kw),
            route=lambda **kw: self._route_after_discussion(**kw),
        )
        self._conversation = GroupConversation(
            groups,
            messages,
            self._targeting,
            ConversationActions(
                history=lambda **kw: self.get_messages(**kw),
                reply=lambda group, member, history, **kw: self._ai_reply(
                    group, member, history, **kw
                ),
                discuss=lambda **kw: self._run_super_discussion_then_route(**kw),
                dispatch=lambda **kw: self._dispatch_work(**kw),
                followup=lambda **kw: self._append_acceptance_followup(**kw),
            ),
            progress_sources,
            make_row,
        )

    async def _execute_employee_work(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        assigned_task: str,
        assignment_focus: str,
        work_order_id: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
    ) -> dict[str, Any]:
        return await self._employee_execution.execute_employee_work(
            group=group,
            member=member,
            task=task,
            assigned_task=assigned_task,
            assignment_focus=assignment_focus,
            work_order_id=work_order_id,
            user_id=user_id,
            sender_name=sender_name,
            branch_context=branch_context,
        )

    def _invoke_super_employee_task(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any]:
        return self._employee_transport.invoke_super_employee_task(
            employee_id=employee_id, task=task, input_data=input_data, user_id=user_id
        )

    def _create_super_employee_relay_task(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None:
        return self._employee_transport.create_super_employee_relay_task(
            employee_id=employee_id, task=task, input_data=input_data, user_id=user_id
        )

    _latest_relay_desktop = staticmethod(EmployeeTransport.latest_relay_desktop)

    @staticmethod
    def _mobile_relay_service() -> MobileRelay:
        return EmployeeTransport.mobile_relay_service()

    @staticmethod
    def _super_employee_service(employee_id: str) -> SuperEmployee:
        return EmployeeTransport.super_employee_service(employee_id)

    _format_work_order_message = staticmethod(ChatFormatting.format_work_order_message)

    def list_groups(self, *, user_id: int, include_hidden: bool = False) -> list[dict[str, Any]]:
        return self._catalog.list_groups(user_id=user_id, include_hidden=include_hidden)

    def _ensure_required_members(self, user_id: int) -> None:
        return self._catalog.ensure_required_members(user_id)

    def _ensure_special_group_names(self, user_id: int) -> None:
        return self._catalog.ensure_special_group_names(user_id)

    def _merge_duplicate_super_development_groups(self, user_id: int) -> None:
        return self._catalog.merge_duplicate_super_development_groups(user_id)

    _canonical_group_name = staticmethod(ChatProjection.canonical_group_name)

    def _backfill_department_members(self, groups: list[dict[str, Any]]) -> None:
        return self._directory.backfill_department_members(groups)

    def list_member_candidates(self) -> list[dict[str, Any]]:
        return self._directory.list_member_candidates()

    def create_group(self, *, user_id: int, name: str) -> dict[str, Any]:
        return self._catalog.create_group(user_id=user_id, name=name)

    def add_member(self, *, user_id: int, group_id: str, member: dict[str, Any]) -> dict[str, Any]:
        return self._catalog.add_member(user_id=user_id, group_id=group_id, member=member)

    def remove_member(self, *, user_id: int, group_id: str, employee_id: str) -> dict[str, Any]:
        return self._catalog.remove_member(
            user_id=user_id, group_id=group_id, employee_id=employee_id
        )

    def toggle_pinned(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.toggle_pinned(user_id=user_id, group_id=group_id)

    def mark_unread(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.mark_unread(user_id=user_id, group_id=group_id)

    def mark_read(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.mark_read(user_id=user_id, group_id=group_id)

    def toggle_followed(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.toggle_followed(user_id=user_id, group_id=group_id)

    def toggle_hidden(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.toggle_hidden(user_id=user_id, group_id=group_id)

    def delete_group(self, *, user_id: int, group_id: str) -> dict[str, Any]:
        return self._catalog.delete_group(user_id=user_id, group_id=group_id)

    def get_messages(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._conversation.get_messages(user_id=user_id, group_id=group_id, limit=limit)

    def _sync_relay_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        return self._progress.sync_relay_progress_for_group(user_id=user_id, group_id=group_id)

    async def post_message(
        self,
        *,
        user_id: int,
        group_id: str,
        text: str,
        sender_name: str = "我",
        mentions: list[str] | None = None,
        dispatch: bool = False,
        branch_context: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._conversation.post_message(
            user_id=user_id,
            group_id=group_id,
            text=text,
            sender_name=sender_name,
            mentions=mentions,
            dispatch=dispatch,
            branch_context=branch_context,
            context=context,
        )

    def _append_acceptance_followup(self, *, user_id: int, group_id: str) -> dict[str, Any] | None:
        return self._work_reports.append_acceptance_followup(user_id=user_id, group_id=group_id)

    _format_acceptance_followup_message = staticmethod(
        ChatFormatting.format_acceptance_followup_message
    )

    def _sync_super_employee_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        return self._progress.sync_super_employee_progress_for_group(
            user_id=user_id, group_id=group_id
        )

    _super_employee_result_message_for_task = staticmethod(
        ProgressSync.super_employee_result_message_for_task
    )

    _super_employee_dispatch_message_for_task = staticmethod(
        ProgressSync.super_employee_dispatch_message_for_task
    )

    _super_employee_task_status = staticmethod(ProgressSync.super_employee_task_status)

    _super_employee_result_task = staticmethod(ProgressSync.super_employee_result_task)

    _latest_progress_row = staticmethod(ProgressSync.latest_progress_row)

    _should_append_progress = staticmethod(ProgressSync.should_append_progress)

    _parse_created_at = staticmethod(ProgressSync.parse_created_at)

    _relay_progress_summary = staticmethod(ChatFormatting.relay_progress_summary)

    _format_relay_progress_message = staticmethod(ChatFormatting.format_relay_progress_message)

    def delete_message(self, *, user_id: int, group_id: str, message_id: str) -> dict[str, Any]:
        return self._conversation.delete_message(
            user_id=user_id, group_id=group_id, message_id=message_id
        )

    def append_relay_work_report(self, *, task: dict[str, Any]) -> dict[str, Any] | None:
        return self._work_reports.append_relay_work_report(task=task)

    _format_work_report_message = staticmethod(ChatFormatting.format_work_report_message)

    def _relay_report_message(
        self, *, user_id: int, group_id: str, task_id: str
    ) -> dict[str, Any] | None:
        return self._work_reports.relay_report_message(
            user_id=user_id, group_id=group_id, task_id=task_id
        )

    def _append_work_acceptance_if_ready(
        self, *, user_id: int, group_id: str, work_order_id: str
    ) -> dict[str, Any] | None:
        return self._work_reports.append_work_acceptance_if_ready(
            user_id=user_id, group_id=group_id, work_order_id=work_order_id
        )

    _format_work_acceptance_message = staticmethod(ChatFormatting.format_work_acceptance_message)

    _report_relay_task_id = staticmethod(ChatFormatting.report_relay_task_id)

    _public_status_label = staticmethod(ChatFormatting.public_status_label)

    _strip_label_from_body = staticmethod(ChatFormatting.strip_label_from_body)

    _relay_task_report = staticmethod(WorkReports.relay_task_report)

    _relay_result_summary = staticmethod(ChatFormatting.relay_result_summary)

    _chat_friendly_summary = staticmethod(ChatFormatting.chat_friendly_summary)

    def _seed_department_groups(self, user_id: int) -> list[dict[str, Any]]:
        return self._directory.seed_department_groups(user_id)

    _parse_routing_json = staticmethod(DispatchTargeting.parse_routing_json)

    _heuristic_dispatch_targets = staticmethod(DispatchTargeting.heuristic_dispatch_targets)

    _dispatch_difficulty = staticmethod(DispatchTargeting.dispatch_difficulty)

    _preferred_single_dispatch_target = staticmethod(
        DispatchTargeting.preferred_single_dispatch_target
    )

    _format_routing_decision_message = staticmethod(
        DispatchTargeting.format_routing_decision_message
    )

    _build_dispatch_assignments = staticmethod(DispatchTargeting.build_dispatch_assignments)

    _super_employee_focus = staticmethod(DispatchTargeting.super_employee_focus)

    _format_assigned_task = staticmethod(DispatchTargeting.format_assigned_task)

    _pick_responders = staticmethod(DispatchTargeting.pick_responders)

    def _pick_dispatch_targets(
        self, members: list[dict[str, Any]], text: str, mentions: list[str] | None
    ) -> list[dict[str, Any]]:
        return self._targeting.pick_dispatch_targets(members, text, mentions)

    _explicit_member_ids = staticmethod(DispatchTargeting.explicit_member_ids)

    _is_broadcast_mention = staticmethod(DispatchTargeting.is_broadcast_mention)

    _should_run_super_discussion = staticmethod(DispatchTargeting.should_run_super_discussion)

    async def _run_super_discussion_then_route(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        user_id: int,
        history: list[dict[str, Any]],
        mentions: list[str] | None,
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return await self._discussion_router.run_super_discussion_then_route(
            group=group,
            task=task,
            candidates=candidates,
            user_id=user_id,
            history=history,
            mentions=mentions,
            persist=persist,
        )

    _xiaoc_dispatch_assessment = staticmethod(GroupDiscussion.xiaoc_dispatch_assessment)

    _discussion_round_count = staticmethod(GroupDiscussion.discussion_round_count)

    async def _super_discussion_reply(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        history: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        round_index: int,
    ) -> str:
        return await self._discussion_router.super_discussion_reply(
            group=group,
            member=member,
            task=task,
            history=history,
            discussion_turns=discussion_turns,
            round_index=round_index,
        )

    _fallback_super_discussion_reply = staticmethod(GroupDiscussion.fallback_super_discussion_reply)

    _discussion_reply_is_placeholder = staticmethod(GroupDiscussion.discussion_reply_is_placeholder)

    async def _route_after_discussion(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        mentions: list[str] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        return await self._discussion_router.route_after_discussion(
            group=group,
            task=task,
            candidates=candidates,
            discussion_turns=discussion_turns,
            mentions=mentions,
        )

    _public_group = staticmethod(ChatProjection.public_group)

    _public_message = staticmethod(ChatProjection.public_message)

    _cap_public_chat_body = staticmethod(ChatProjection.cap_public_chat_body)

    _clean_public_chat_body = staticmethod(ChatProjection.clean_public_chat_body)

    _compact_public_acceptance_body = staticmethod(ChatProjection.compact_public_acceptance_body)

    def _message_row(
        self,
        *,
        user_id: int,
        group_id: str,
        role: str,
        sender_id: str,
        sender_name: str,
        sender_avatar: str,
        body: str,
        kind: str = "chat",
        status: str = "",
        work_order_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return ChatProjection.message_row(
            user_id=user_id,
            group_id=group_id,
            role=role,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_avatar=sender_avatar,
            body=body,
            kind=kind,
            status=status,
            work_order_id=work_order_id,
            payload=payload,
        )

    def _latest_previews(self, user_id: int) -> dict[str, dict[str, Any]]:
        return ChatProjection.latest_previews(self._read_messages(), user_id)

    def _user_groups(self, user_id: int) -> list[dict[str, Any]]:
        return self._storage.user_groups(user_id)

    _dedupe_groups_by_id = staticmethod(GroupChatRepository.dedupe_groups_by_id)

    def _compact_groups_file_if_needed(self) -> None:
        return self._storage.compact_groups_file_if_needed()

    def _all_groups(self) -> list[dict[str, Any]]:
        return self._storage.all_groups()

    def _read_messages(self) -> list[dict[str, Any]]:
        return self._storage.read_messages()

    @staticmethod
    def _message_cipher() -> Fernet:
        return GroupChatRepository.message_cipher()

    @staticmethod
    def _desktop_data_dir_secret(data_dir: str) -> str:
        return GroupChatRepository.desktop_data_dir_secret(data_dir)

    @staticmethod
    def _process_local_secret() -> str:
        return GroupChatRepository.process_local_secret()

    @staticmethod
    def _legacy_derived_cipher() -> Fernet | None:
        return GroupChatRepository.legacy_derived_cipher()

    def _encrypted_message_line(self, message: dict[str, Any]) -> str:
        return self._storage.encrypted_message_line(message)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        return self._storage.read_jsonl(path)

    def _append_group(self, group: dict[str, Any]) -> None:
        return self._storage.append_group(group)

    def _rewrite_groups(self, groups: list[dict[str, Any]]) -> None:
        return self._storage.rewrite_groups(groups)

    def _append_messages(self, messages: list[dict[str, Any]]) -> None:
        return self._storage.append_messages(messages)

    def _rewrite_messages(self, messages: list[dict[str, Any]]) -> None:
        return self._storage.rewrite_messages(messages)

    def _resolve_group_id(self, *, user_id: int, group_id: str) -> str:
        return self._storage.resolve_group_id(user_id=user_id, group_id=group_id)

    _find = staticmethod(GroupChatRepository.find)

    _replace = staticmethod(GroupChatRepository.replace)

    _clean_chat_summary_line = staticmethod(ChatFormatting.clean_chat_summary_line)

    _relay_result_risk = staticmethod(ChatFormatting.relay_result_risk)

    _effective_report_status = staticmethod(ExecutionResultPolicy.effective_report_status)

    _summary_indicates_unfinished = staticmethod(ExecutionResultPolicy.summary_indicates_unfinished)

    _summary_indicates_failed = staticmethod(ExecutionResultPolicy.summary_indicates_failed)

    _completed_report_lacks_required_evidence = staticmethod(
        ExecutionResultPolicy.completed_report_lacks_required_evidence
    )

    _task_requires_execution_evidence = staticmethod(
        ExecutionResultPolicy.task_requires_execution_evidence
    )

    _has_execution_evidence = staticmethod(ExecutionResultPolicy.has_execution_evidence)

    _execution_evidence_text = staticmethod(ExecutionResultPolicy.execution_evidence_text)

    _summary_is_research_only_without_evidence = staticmethod(
        ExecutionResultPolicy.summary_is_research_only_without_evidence
    )

    _relay_result_dispatch_value = staticmethod(ExecutionResultPolicy.relay_result_dispatch_value)

    _execution_summary = staticmethod(ExecutionResultPolicy.execution_summary)

    _execution_risk = staticmethod(ExecutionResultPolicy.execution_risk)

    _stringify_summary = staticmethod(ExecutionResultPolicy.stringify_summary)

    _compact_result = staticmethod(ExecutionResultPolicy.compact_result)

    async def _super_employee_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        return await self._replies.super_employee_reply(group, member, history, user_id=user_id)

    async def _ai_reply(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str:
        return await self._replies.ai_reply(group, member, history, user_id=user_id)

    async def _dispatch_work(
        self,
        *,
        group: dict[str, Any],
        members: list[dict[str, Any]],
        task: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return await self._work_dispatch.dispatch_work(
            group=group,
            members=members,
            task=task,
            user_id=user_id,
            sender_name=sender_name,
            branch_context=branch_context,
            persist=persist,
        )

    def _initial_relay_progress_from_report(
        self, *, user_id: int, group_id: str, report_row: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self._work_dispatch.initial_relay_progress_from_report(
            user_id=user_id, group_id=group_id, report_row=report_row
        )


__all__ = [
    "AiGroupChatService",
    "CHAT_ACCEPTANCE_SUMMARY_CHARS",
    "CHAT_REPORT_SUMMARY_CHARS",
    "MAX_RESPONDERS",
    "PUBLIC_ACCEPTANCE_BODY_MAX_CHARS",
    "PUBLIC_CHAT_BODY_MAX_CHARS",
    "SUPER_DISCUSSION_DEFAULT_ROUNDS",
    "SUPER_DISCUSSION_MAX_ROUNDS",
]
