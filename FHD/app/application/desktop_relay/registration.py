"""Cloud-confirmed pairing and a public view of the persisted desktop binding."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from app.application.desktop_relay.protocols import (
    ApiUrlCall,
    ConditionalConfigUpdate,
    HttpClientFactory,
    JsonObject,
    ReadConfig,
    RelayBinding,
    WriteConfig,
)


@dataclass(frozen=True)
class RegistrationPorts:
    read_config: ReadConfig
    write_config: WriteConfig
    update_config: ConditionalConfigUpdate
    replace_config: ConditionalConfigUpdate
    base_url: Callable[[], str]
    api_url: ApiUrlCall
    http_client: HttpClientFactory
    now: Callable[[], float]
    environment: Callable[[], Mapping[str, str]]
    device_id: Callable[[], str]
    hostname: Callable[[], str]
    platform: Callable[[], str]
    start_poller: Callable[[], bool]
    public_payload: Callable[[JsonObject], JsonObject | None]


@dataclass(frozen=True)
class RenewalResult:
    supported: bool
    payload: JsonObject | None = None


class RelayRegistration:
    def __init__(self, ports: RegistrationPorts, logger: logging.Logger) -> None:
        self.ports = ports
        self.logger = logger

    def public_payload(self, config: JsonObject) -> JsonObject | None:
        relay_id = str(config.get("relay_id") or "").strip()
        pairing_code = str(config.get("pairing_code") or "").strip()
        if not relay_id or not pairing_code:
            return None
        base_url = str(config.get("relay_base_url") or "").strip() or self.ports.base_url()
        exp = int(config.get("exp") or 0)
        if exp <= 0:
            registered_at = int(config.get("registered_at") or 0)
            if registered_at > 0:
                exp = registered_at + int(
                    self.ports.environment().get("XCAGI_RELAY_PAIRING_TTL_SEC") or "86400"
                )
        if exp > 0 and exp <= int(self.ports.now()):
            return None
        expires_at = str(config.get("expires_at") or "").strip()
        return {
            "relay_id": relay_id,
            "pairing_code": pairing_code,
            "paired": bool(config.get("paired")),
            "mobile_username": str(config.get("mobile_username") or "").strip(),
            "last_relay_sync_at": int(config.get("last_relay_sync_at") or 0),
            **({"expires_at": expires_at} if expires_at else {}),
            **({"exp": exp} if exp > 0 else {}),
            "relay_base_url": base_url,
            "qr_json": {
                "v": 3,
                "kind": "xcagi_relay_pairing",
                "relay_id": relay_id,
                "code": pairing_code,
                "t": pairing_code,
                "relay_base_url": base_url,
            },
        }

    def cached_payload(self) -> JsonObject | None:
        config = self.ports.read_config()
        payload = self.ports.public_payload(config)
        if payload is not None:
            return payload
        if not config.get("paired"):
            return None
        relay_id = str(config.get("relay_id") or "").strip()
        if not relay_id:
            return None
        return {
            "relay_id": relay_id,
            "relay_base_url": str(config.get("relay_base_url") or "") or self.ports.base_url(),
            "paired": True,
            "mobile_username": str(config.get("mobile_username") or "").strip(),
            "last_relay_sync_at": int(config.get("last_relay_sync_at") or 0),
        }

    def _renew(self, config: JsonObject) -> RenewalResult:
        binding = RelayBinding.from_config(config, self.ports.base_url())
        try:
            with self.ports.http_client(5) as client:
                response = client.post(
                    self.ports.api_url("/api/mobile/v1/relay/desktop/renew", binding.base_url),
                    json={"relay_id": binding.relay_id, "desktop_token": binding.desktop_token},
                )
                if response.status_code == 405:
                    return RenewalResult(supported=False)
                response.raise_for_status()
                data = response.json().get("data")
        except (httpx.HTTPError, ValueError, KeyError, AttributeError) as exc:
            self.logger.warning("mobile relay pairing renewal failed: %s", exc)
            return RenewalResult(supported=True)
        code = str(data.get("pairing_code") or "").strip() if isinstance(data, dict) else ""
        if (
            not isinstance(data, dict)
            or data.get("relay_id") != binding.relay_id
            or len(code) != 6
            or not code.isdigit()
        ):
            return RenewalResult(supported=True)
        updated = self.ports.update_config(
            binding, {**data, "registered_at": int(self.ports.now())}
        )
        if updated is None:
            return RenewalResult(supported=True)
        self.ports.start_poller()
        return RenewalResult(supported=True, payload=self.ports.public_payload(updated))

    def register(
        self, *, host: str, port: int, label: str = "", force_new: bool = False
    ) -> JsonObject | None:
        previous: RelayBinding | None = None
        if not force_new:
            existing = self.ports.read_config()
            previous = RelayBinding.from_config(existing, self.ports.base_url())
            if previous.valid:
                renewed = self._renew(existing)
                if renewed.supported:
                    return renewed.payload
                self.logger.warning("cloud relay lacks the renew endpoint; re-registering desktop")
        base_url = self.ports.base_url()
        device_label = label.strip() or f"XCAGI 桌面执行端 - {self.ports.hostname()}"
        body = {
            "label": device_label,
            "device_id": self.ports.device_id(),
            "relay_base_url": base_url,
            "capabilities": {
                "codex": True,
                "codex_cli": True,
                "claude": True,
                "claude_cli": True,
                "cursor": True,
                "cursor_cli": True,
                "trae": True,
                "trae_cli": True,
                "desktop": True,
                "host": host,
                "port": int(port),
                "platform": self.ports.platform(),
            },
        }
        timeout = float(self.ports.environment().get("XCAGI_RELAY_REGISTER_TIMEOUT_SEC") or "5")
        try:
            with self.ports.http_client(timeout) as client:
                response = client.post(
                    self.ports.api_url("/api/mobile/v1/relay/desktop/register", base_url), json=body
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.InvalidURL, httpx.UnsupportedProtocol, ValueError) as exc:
            self.logger.warning("mobile relay desktop register rejected invalid request: %s", exc)
            return None
        except httpx.HTTPError as exc:
            self.logger.warning("mobile relay desktop register failed: %s", exc)
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        code = str(data.get("pairing_code") or "").strip() if isinstance(data, dict) else ""
        if (
            not isinstance(data, dict)
            or not data.get("desktop_token")
            or not data.get("relay_id")
            or len(code) != 6
            or not code.isdigit()
        ):
            self.logger.warning("mobile relay desktop register returned invalid payload")
            return None
        config = {
            "relay_id": str(data.get("relay_id") or ""),
            "desktop_token": str(data.get("desktop_token") or ""),
            "relay_base_url": str(data.get("relay_base_url") or base_url),
            "pairing_code": str(data.get("pairing_code") or ""),
            "expires_at": str(data.get("expires_at") or ""),
            "exp": int(data.get("exp") or 0),
            "registered_at": int(self.ports.now()),
            "label": device_label,
        }
        if previous is None:
            self.ports.write_config(config)
        elif self.ports.replace_config(previous, config) is None:
            return None
        self.ports.start_poller()
        return data
