# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_autonomy_service")


def propose_employee_pack(
    signals: _facade().Dict[str, _facade().Any]
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    return _facade()._employee_pack_proposal.propose_employee_pack(
        signals, llm_call=_facade()._call_llm
    )
