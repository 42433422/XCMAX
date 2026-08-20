# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart01MixinPart03Mixin:
    def _para_request(
        self,
        client: _facade().httpx.Client,
        api_url: str,
        token: str,
        method: str,
        path: str,
        *,
        json_body: dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        resp = client.request(
            method,
            f"{api_url}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
        body = self._json_response(resp)
        if resp.status_code >= 400:
            raise RuntimeError(self._error_message(body, f"Para API 请求失败 ({resp.status_code})"))
        return body

    def _device_eligible(self, item: _facade().Any) -> bool:
        """单台设备能否承接派工：在线 + 目标工具已装且非占用 + 具备能力。

        一级(本机单设备)与二级(多设备)选择共用此判定；不含 target_devices
        过滤(由各调用方按需另行处理)。
        """
        if not isinstance(item, dict):
            return False
        if str(item.get("status") or "") != "online":
            return False
        tool = self._device_tool(item, self._p.tool_name)
        if tool and str(tool.get("status") or "") == "not_installed":
            return False
        if tool and str(tool.get("status") or "") == "running" and tool.get("currentTask"):
            return False
        capabilities = (
            item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {}
        )
        if not isinstance(capabilities, dict):
            capabilities = {}
        if not tool and capabilities.get(self._p.capability_key) is not True:
            return False
        return True

    def _select_para_devices(
        self, devices: list[_facade().Any], request: dict[str, _facade().Any]
    ) -> list[dict[str, _facade().Any]]:
        target_devices = request.get("target_devices")
        targets = (
            {str(item).strip() for item in target_devices if str(item).strip()}
            if isinstance(target_devices, list)
            else {"all"}
        )
        candidates: list[dict[str, _facade().Any]] = []
        for item in devices:
            if not self._device_eligible(item):
                continue
            if (
                "all" not in targets
                and str(item.get("id") or "") not in targets
                and (str(item.get("name") or "") not in targets)
            ):
                continue
            candidates.append(item)
        workers = [item for item in candidates if not item.get("isPrimary")]
        selected = workers or candidates
        max_devices = self._max_para_devices(request)
        return selected[:max_devices]

    def _local_device_id(self) -> str:
        """配置的本机设备 ID(可选)。未配则按 is_primary / 首台合格设备兜底。"""
        return (
            _facade().os.environ.get(f"{self._p.env_super_prefix}_DEVICE_ID")
            or _facade().os.environ.get("MODSTORE_PARA_DEVICE_ID")
            or _facade().os.environ.get("DEVFLEET_DEVICE_ID")
            or ""
        ).strip()
