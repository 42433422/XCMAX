"""Compat module path: debt19 renamed ports → customer_service_ports."""

from __future__ import annotations

from app.mod_sdk.customer_service.customer_service_ports import (  # noqa: F401
    Payload,
    Employee,
    Environment,
    MessageSender,
    PipelineRepository,
    PipelineServices,
    IntakeServices,
    CrmServices,
    ChangesServices,
    DeliveryServices,
    ContractsServices,
    MessagingServices,
)

__all__ = [
    "Payload",
    "Employee",
    "Environment",
    "MessageSender",
    "PipelineRepository",
    "PipelineServices",
    "IntakeServices",
    "CrmServices",
    "ChangesServices",
    "DeliveryServices",
    "ContractsServices",
    "MessagingServices",
]
