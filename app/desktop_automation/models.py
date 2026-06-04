"""AppProfile / workflow / element 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ElementDef:
    role: str = "button"
    vlm_hint: str = ""
    fallback_norm: tuple[float, float] | None = None
    fallback_norm_mac: tuple[float, float] | None = None
    yolo_class: str | None = None


@dataclass
class AppProfile:
    app_id: str
    label: str = ""
    window_match: dict[str, list[str]] = field(default_factory=dict)
    elements: dict[str, ElementDef] = field(default_factory=dict)
    workflows: dict[str, list[str]] = field(default_factory=dict)
    driver_preference: str = "auto"  # auto | native | mcp_wechat | mcp_custom
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppProfile:
        elements: dict[str, ElementDef] = {}
        for key, val in (data.get("elements") or {}).items():
            if isinstance(val, dict):
                fb = val.get("fallback_norm")
                fb_mac = val.get("fallback_norm_mac")
                elements[key] = ElementDef(
                    role=str(val.get("role") or "button"),
                    vlm_hint=str(val.get("vlm_hint") or ""),
                    fallback_norm=tuple(fb)
                    if isinstance(fb, (list, tuple)) and len(fb) == 2
                    else None,
                    fallback_norm_mac=tuple(fb_mac)
                    if isinstance(fb_mac, (list, tuple)) and len(fb_mac) == 2
                    else None,
                    yolo_class=val.get("yolo_class"),
                )
        return cls(
            app_id=str(data.get("app_id") or ""),
            label=str(data.get("label") or data.get("app_id") or ""),
            window_match=dict(data.get("window_match") or {}),
            elements=elements,
            workflows={k: list(v) for k, v in (data.get("workflows") or {}).items()},
            driver_preference=str(data.get("driver_preference") or "auto"),
            extra={
                k: v
                for k, v in data.items()
                if k
                not in (
                    "app_id",
                    "label",
                    "window_match",
                    "elements",
                    "workflows",
                    "driver_preference",
                )
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "label": self.label,
            "window_match": self.window_match,
            "elements": {
                k: {
                    "role": v.role,
                    "vlm_hint": v.vlm_hint,
                    **({"fallback_norm": list(v.fallback_norm)} if v.fallback_norm else {}),
                    **(
                        {"fallback_norm_mac": list(v.fallback_norm_mac)}
                        if v.fallback_norm_mac
                        else {}
                    ),
                    **({"yolo_class": v.yolo_class} if v.yolo_class else {}),
                }
                for k, v in self.elements.items()
            },
            "workflows": self.workflows,
            "driver_preference": self.driver_preference,
            **self.extra,
        }


@dataclass
class WindowInfo:
    platform: str
    x: int
    y: int
    width: int
    height: int
    title: str = ""
    handle: Any = None

    @property
    def size_hash(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass
class ElementMatch:
    element_id: str
    screen_x: int
    screen_y: int
    confidence: float
    source: str  # template | yolo | cache | fallback | ocr


@dataclass
class WorkflowResult:
    success: bool
    workflow: str
    app_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    need_bootstrap: bool = False
    error: str = ""
