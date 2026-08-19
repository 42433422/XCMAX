"""Dispatch and routing facade for AI group chat."""

from __future__ import annotations

from app.application.group_chat.discussion_router import DiscussionRoutingMixin
from app.application.group_chat.dispatch_targeting import DispatchTargetingMixin
from app.application.group_chat.work_dispatch import WorkDispatchMixin


class AiGroupChatDispatchMixin(DiscussionRoutingMixin, DispatchTargetingMixin, WorkDispatchMixin):
    """Compose discussion, target selection, and work execution behavior."""
