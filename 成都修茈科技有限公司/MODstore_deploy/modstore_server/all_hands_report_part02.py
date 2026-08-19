# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.all_hands_report")


def _craft_workshop_pkg_ids() -> frozenset[str]:
    try:
        from modstore_server.duty_roster import YUANGON_AREAS

        ids = YUANGON_AREAS.get("craft-workshop", {}).get("ids") or []
        return frozenset((str(x).strip() for x in ids if str(x).strip()))
    except Exception:
        return frozenset(
            {
                "intent-analyst",
                "employee-planner",
                "artifact-generator",
                "quality-validator",
                "miniapp-builder",
                "script-binder",
                "workflow-automator",
                "pack-registrar",
                "sandbox-tester",
                "code-validator",
                "self-checker",
                "host-checker",
                "hex-quality-assessor",
            }
        )
