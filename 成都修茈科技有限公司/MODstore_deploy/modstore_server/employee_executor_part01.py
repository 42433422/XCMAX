# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_executor")


def _emp_im_notify_boss(employee_id: str, manifest: _facade().Any, body: str, hook: str) -> None:
    """员工执行管道 hook 公共入口：从 manifest 抽 display_name + mod_id，调 notify_boss。

    best-effort：任何异常只 log debug，不抛错。body 为空也跳过。
    4 个 hook 点（perception/cognition/verification/handoff）共用此 helper。
    """
    body_text = (body or "").strip()
    if not body_text:
        return
    try:
        from modstore_server.employee_im_bridge import notify_boss as _notify_boss_im

        _emp_display = ""
        _emp_mod_id = ""
        try:
            if isinstance(manifest, dict):
                _ident = (
                    manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
                )
                _emp_display = str(_ident.get("name") or manifest.get("name") or "").strip()
                _emp_mod_id = str(manifest.get("mod_id") or manifest.get("id") or "").strip()
        except Exception:
            _facade().logger.debug("emp_im_notify manifest parse skipped", exc_info=True)
        _notify_boss_im(
            employee_id,
            body=body_text[:600],
            hook=hook,
            mod_id=_emp_mod_id,
            display_name=_emp_display,
        )
    except Exception:
        _facade().logger.debug("emp_im_notify %s skipped", hook, exc_info=True)
