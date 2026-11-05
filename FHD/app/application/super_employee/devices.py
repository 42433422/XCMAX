"""Pure device eligibility and tier-selection policy; no scheduler I/O."""

from __future__ import annotations

import os
from typing import Any

from .profiles import SuperEmployeeToolProfile


class DeviceSelection:
    def __init__(self, profile: SuperEmployeeToolProfile) -> None:
        self._p = profile

    def device_eligible(self, item: Any) -> bool:
        """单台设备能否承接派工：在线 + 目标工具已装且非占用 + 具备能力。

        一级(本机单设备)与二级(多设备)选择共用此判定；不含 target_devices
        过滤(由各调用方按需另行处理)。
        """
        if not isinstance(item, dict):
            return False
        if str(item.get("status") or "") != "online":
            return False
        tool = self.device_tool(item, self._p.tool_name)
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

    def select_para_devices(
        self, devices: list[Any], request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        target_devices = request.get("target_devices")
        targets = (
            {str(item).strip() for item in target_devices if str(item).strip()}
            if isinstance(target_devices, list)
            else {"all"}
        )
        candidates: list[dict[str, Any]] = []
        for item in devices:
            if not self.device_eligible(item):
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
        max_devices = self.max_para_devices(request)
        return selected[:max_devices]

    def local_device_id(self) -> str:
        """配置的本机设备 ID(可选)。未配则按 is_primary / 首台合格设备兜底。"""
        return (
            os.environ.get(f"{self._p.env_super_prefix}_DEVICE_ID")
            or os.environ.get("MODSTORE_PARA_DEVICE_ID")
            or os.environ.get("DEVFLEET_DEVICE_ID")
            or ""
        ).strip()

    def resolve_para_tier(self, request: dict[str, Any]) -> int:
        """决定该请求走一级(1)还是二级(2)。默认一级，按需升二级。"""
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        forced = (
            (
                os.environ.get(f"{self._p.env_super_prefix}_PARA_FORCE_TIER")
                or os.environ.get("MODSTORE_PARA_FORCE_TIER")
                or ""
            )
            .strip()
            .lower()
        )
        if forced in {"1", "local", "single", "本机"}:
            return 1
        if forced in {"2", "fleet", "multi", "多设备"}:
            return 2
        if not isinstance(raw_context, dict):
            raw_context = {}
        tier_hint = (
            str(raw_context.get("para_tier") or raw_context.get("tier") or "").strip().lower()
        )
        if tier_hint in {"2", "fleet", "multi", "multi_device", "多设备"}:
            return 2
        if tier_hint in {"1", "local", "single", "本机"}:
            return 1
        if raw_context.get("escalate") in (True, 1, "1", "true", "yes", "on"):
            return 2
        try:
            if int(raw_context.get("max_devices") or 0) > 1:
                return 2
        except (TypeError, ValueError):
            pass
        target = request.get("target_devices")
        if isinstance(target, list):
            specific = [s for s in (str(x).strip() for x in target) if s and s != "all"]
            if len(specific) > 1:
                return 2
        text = f"{request.get('task') or ''} {request.get('prompt') or ''}"
        if any(m in text for m in ("多设备", "所有设备", "全部设备", "调用所有设备", "跨设备")):
            return 2
        return 1

    def select_local_device(
        self, devices: list[Any], request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """一级：只挑「本机」一台设备。

        本机识别优先级：① 配置的本机 device_id；② is_primary 主设备；③ 都无从
        识别时退而取首台合格设备(单设备派工)。识别到的本机若不合格(离线/工具未装/
        占用)则返回空，由上层 _select_devices_by_tier 升二级到其它设备——这正是
        「本机无 CLI → 升二级」的语义所在。
        """
        local_id = self.local_device_id()
        if local_id:
            for item in devices:
                if isinstance(item, dict) and str(item.get("id") or "") == local_id:
                    return [item] if self.device_eligible(item) else []
            return []
        for item in devices:
            if isinstance(item, dict) and item.get("isPrimary"):
                return [item] if self.device_eligible(item) else []
        for item in devices:
            if self.device_eligible(item):
                return [item]
        return []

    def select_devices_by_tier(
        self, devices: list[Any], request: dict[str, Any]
    ) -> tuple[int, list[dict[str, Any]]]:
        """按 tier 选设备，返回 (实际 tier, 选中设备列表)。

        一级优先：先选本机单设备；本机无合格设备则自动升二级选多设备。
        """
        tier = self.resolve_para_tier(request)
        if tier == 1:
            local = self.select_local_device(devices, request)
            if local:
                return (1, local)
            return (2, self.select_para_devices(devices, request))
        return (2, self.select_para_devices(devices, request))

    def max_para_devices(self, request: dict[str, Any]) -> int:
        raw_context = (
            request.get("raw_context") if isinstance(request.get("raw_context"), dict) else {}
        )
        if not isinstance(raw_context, dict):
            raw_context = {}
        value = (
            raw_context.get("max_devices")
            or os.environ.get(f"{self._p.env_super_prefix}_MAX_DEVICES")
            or 3
        )
        try:
            return max(1, min(8, int(value)))
        except (TypeError, ValueError):
            return 3

    def device_tool(self, device: dict[str, Any], name: str) -> dict[str, Any] | None:
        tools = device.get("tools")
        if not isinstance(tools, list):
            return None
        for tool in tools:
            if isinstance(tool, dict) and tool.get("toolName") == name:
                return tool
        return None
