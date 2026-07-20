"""Application boundary for the local Kellai customer-inbox integration."""

from __future__ import annotations

from typing import Any

from app.services import kellai_binding_store, kellai_customer_copilot

KellaiCopilotError = kellai_customer_copilot.KellaiCopilotError


def binding_status() -> dict[str, Any]:
    return kellai_binding_store.status()


def start_pairing() -> dict[str, Any]:
    return kellai_binding_store.start_pairing()


def pending_for_kellai() -> dict[str, Any] | None:
    return kellai_binding_store.pending_for_kellai()


def approve_pairing(**kwargs: Any) -> dict[str, Any]:
    return kellai_binding_store.approve_pairing(**kwargs)


def cancel_pairing(**kwargs: Any) -> None:
    kellai_binding_store.cancel_pairing(**kwargs)


def connection_credentials() -> dict[str, Any] | None:
    return kellai_binding_store.connection_credentials()


def disconnect() -> None:
    kellai_binding_store.disconnect()


def purge_all(*, actor: int | str | None = None) -> None:
    kellai_customer_copilot.purge_all(actor=actor)


def latest_draft(customer_id: int) -> dict[str, Any] | None:
    return kellai_customer_copilot.latest_draft(customer_id)


def list_follow_up_tasks(customer_id: int) -> list[dict[str, Any]]:
    return kellai_customer_copilot.list_follow_up_tasks(customer_id)


def follow_up_metrics(customer_id: int) -> dict[str, Any]:
    return kellai_customer_copilot.follow_up_metrics(customer_id)


async def generate_draft(**kwargs: Any) -> dict[str, Any]:
    return await kellai_customer_copilot.generate_draft(**kwargs)


def decide_draft(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.decide_draft(**kwargs)


def create_follow_up_task(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.create_follow_up_task(**kwargs)


def decide_follow_up_task(**kwargs: Any) -> dict[str, Any]:
    return kellai_customer_copilot.decide_follow_up_task(**kwargs)
