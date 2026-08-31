# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def _digest_kpi_cards_html(
    *, met_ok: int, met_fail: int, emp_n: int, ops_n: int, inc_n: int, event_n: int
) -> str:
    """邮件顶部 KPI 卡片区：4 个核心指标，图标 + 大数字 + 顶部强调条 + 颜色编码。"""
    cards: _facade().List[str] = []

    def _card(
        value: str,
        label: str,
        *,
        icon: str,
        accent: str,
        color: str,
        bg: str,
        border: str,
        sub: str = "",
        sub_color: str = "#94a3b8",
    ) -> str:
        sub_html = (
            f'<div style="font-size:11px;color:{sub_color};margin-top:3px;font-weight:600">{sub}</div>'
            if sub
            else ""
        )
        return f'<td style="width:25%;padding:5px;vertical-align:top"><div style="border-radius:12px;border:1px solid {border};background:{bg};overflow:hidden"><div style="height:3px;background:{accent};line-height:3px;font-size:0">&nbsp;</div><div style="padding:13px 8px 14px;text-align:center"><div style="font-size:17px;line-height:1">{icon}</div><div style="font-size:27px;font-weight:800;color:{color};line-height:1.15;margin-top:3px;font-variant-numeric:tabular-nums">{value}</div><div style="font-size:11px;color:#64748b;margin-top:5px;font-weight:600">{label}</div>{sub_html}</div></div></td>'

    cards.append(
        _card(
            str(emp_n),
            "编制在岗",
            icon="&#x1F465;",
            accent="#2563eb",
            color="#1d4ed8",
            bg="#eff6ff",
            border="#bfdbfe",
        )
    )
    if met_fail == 0:
        cards.append(
            _card(
                str(met_ok),
                "任务成功",
                icon="&#x2705;",
                accent="#16a34a",
                color="#047857",
                bg="#ecfdf5",
                border="#a7f3d0",
                sub="全部成功",
                sub_color="#16a34a",
            )
        )
    else:
        cards.append(
            _card(
                str(met_ok),
                "任务成功",
                icon="&#x26A0;&#xFE0F;",
                accent="#ea580c",
                color="#c2410c",
                bg="#fff7ed",
                border="#fed7aa",
                sub=f"失败 {met_fail} 次",
                sub_color="#ea580c",
            )
        )
    if ops_n == 0:
        cards.append(
            _card(
                "0",
                "运维操作",
                icon="&#x1F6E0;&#xFE0F;",
                accent="#94a3b8",
                color="#64748b",
                bg="#f8fafc",
                border="#e2e8f0",
            )
        )
    else:
        cards.append(
            _card(
                str(ops_n),
                "运维操作",
                icon="&#x1F6E0;&#xFE0F;",
                accent="#2563eb",
                color="#1d4ed8",
                bg="#eff6ff",
                border="#bfdbfe",
            )
        )
    if inc_n == 0:
        cards.append(
            _card(
                "0",
                "待处理事件",
                icon="&#x1F514;",
                accent="#16a34a",
                color="#047857",
                bg="#ecfdf5",
                border="#a7f3d0",
                sub=f"事件总量 {event_n} 条",
                sub_color="#16a34a",
            )
        )
    else:
        cards.append(
            _card(
                str(inc_n),
                "待处理事件",
                icon="&#x1F514;",
                accent="#ea580c",
                color="#c2410c",
                bg="#fff7ed",
                border="#fed7aa",
                sub=f"事件总量 {event_n} 条",
                sub_color="#ea580c",
            )
        )
    return (
        '<table role="presentation" style="width:100%;border-collapse:collapse;margin:0"><tr>'
        + "".join(cards)
        + "</tr></table>"
    )
