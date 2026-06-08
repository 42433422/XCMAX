"""Notification domain.

Pure domain types and ports for the notification bounded context. No
framework, ORM or HTTP imports — those belong in :mod:`application` and
:mod:`infrastructure`. The ``test_neuro_ddd_boundaries`` suite enforces
that rule.
"""

from .ports import NotificationRepository, RealtimePusher
from .types import Notification, NotificationType, OutboundNotification

__all__ = [
    "Notification",
    "NotificationRepository",
    "NotificationType",
    "OutboundNotification",
    "RealtimePusher",
]
