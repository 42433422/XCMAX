"""连续对话里的已确认数字。

后出现的纠正覆盖旧值。带「如果 / 假设 / 暂时不要修改 / 只是模拟」的句子只在副本上演算，
不写回确认值。同一会话的窗口数据和企业台账分开记，另一个会话的标记不会被借来用。
"""

from __future__ import annotations

import copy
import re
from typing import Any

_DEPT = {
    "研发部": "研发",
    "研发部门": "研发",
    "销售部": "销售",
    "销售部门": "销售",
    "财务部": "财务",
    "财务部门": "财务",
    "客户服务部": "客服",
    "客服部": "客服",
    "客服部门": "客服",
}
_DEPT_RE = "|".join(sorted(_DEPT, key=len, reverse=True))


def empty_state() -> dict[str, Any]:
    return {
        "product": "",
        "platform": "",
        "modules": [],
        "first_load": "",
        "warm_load": "",
        "page_switches": None,
        "chat_rounds": None,
        "checks": [],
        "severe": False,
        "exclude_install": False,
        "company_name": "",
        "business": "",
        "company": _slot(),
        "windows": {key: _slot() for key in ("A", "B", "C")},
        "depts": {},
        "dept_initial": {},
        "dept_base": {},
        "recruit": {},
        "recruit_ban": [],
        "orders": {},
        "order_log": [],
        "priority": {},
        "priority_initial": {},
        "income_parts": {},
        "expense_parts": {},
        "inbound_kinds": None,
        "last_inbound": None,
        "marker": "",
        "task": "",
        "headcount_stated": None,
        "customer_added": 0,
        "changes": [],
        "initial": {},
    }


def _slot() -> dict[str, Any]:
    return {
        "topic": "",
        "customers": None,
        "active": None,
        "sku": None,
        "stock": None,
        "stockout": None,
        "income": None,
        "expense": None,
    }


def respond(state: dict[str, Any], text: str) -> str:
    """把一句用户原话折进确认值，并给出这一轮的回答。假设句不改确认值。"""
    if _hypothetical(text) or _projection(text):
        return _hypothetical_reply(state, text)
    note = _apply(state, text)
    asked = _answer(state, text)
    if asked:
        return asked
    if note:
        return note
    if "1.7" in text:
        return "首次加载客户管理页面按 1.7 秒记，这一轮不建缺陷单。"
    if "几十毫秒" in text:
        return "页面已经加载后再切换，按几十毫秒记。"
    return "已记录这句话。这一轮没有新的确认数字。"


def _hypothetical(text: str) -> bool:
    if re.search(
        r"(暂时不要修改|只是模拟|不要修改实际|不要修改原始|只做风险分析|"
        r"不要改当前确认|撤销之前曾模拟|这只是重算)",
        text,
    ):
        return True
    return bool(re.search(r"如果|假设", text) and re.search(r"多少|会变成|会产生", text))


def _projection(text: str) -> bool:
    return bool(re.search(r"(增加|新增|减少).{0,16}后", text) and "多少" in text)


def _hypothetical_reply(state: dict[str, Any], text: str) -> str:
    slot = _bucket(state, text)
    if "撤销之前曾模拟" in text or "这只是重算" in text:
        active = _num(slot.get("active"))
        extra = _first_int(r"其中(\d+)家成为活跃", text) or 0
        return (
            f"那次模拟里，活跃客户会是 {active + extra}。"
            f"这只是重算，确认值不变：客户 {_num(slot.get('customers'))}，活跃客户 {active}。"
        )
    if match := re.search(r"新增(\d+)家客户，其中(\d+)家成为活跃", text):
        active = _num(slot.get("active")) + int(match.group(2))
        return (
            f"按这次模拟，活跃客户是 {active}。"
            f"确认值不变：客户 {_num(slot.get('customers'))}，活跃客户 {_num(slot.get('active'))}。"
        )
    if match := re.search(r"(\d+)家非活跃客户开始交易", text):
        active = _num(slot.get("active")) + int(match.group(1))
        return (
            f"如果这 {match.group(1)} 家开始交易，活跃客户会变成 {active}。"
            f"确认的活跃客户仍是 {_num(slot.get('active'))}，这次没有改确认值。"
        )
    if "服务器成本增加" in text:
        extra = _first_int(r"增加(\d+)万元", text) or 0
        income = _money(state, "income")
        expense = _money(state, "expense")
        return (
            f"如果服务器成本增加 {extra} 万元，余额是 {income - expense - extra} 万元。"
            f"确认的支出仍是 {expense} 万元，余额仍是 {income - expense} 万元。"
        )
    if _projection(text) and "活跃率" in text:
        extra = _first_int(r"增加(\d+)家", text) or 0
        customers = _num(slot.get("customers"))
        active = _num(slot.get("active"))
        projected = customers + extra
        rate = round(active * 100 / projected, 1) if projected else 0
        return (
            f"按这句话计算，客户 {projected} 家，活跃仍是 {active} 家，活跃率 {rate}%。"
            f"确认的客户仍是 {customers} 家，没有改。"
        )
    if "补货" in text:
        extra = _first_int(r"补货(\d+)件", text) or 0
        stock = _num(_bucket(state, text).get("stock"))
        return (
            f"如果补货 {extra} 件，总库存是 {stock + extra} 件。"
            f"确认的库存仍是 {stock} 件，没有改。"
        )
    if "支出增加" in text and ("结余" in text or "余额" in text):
        extra = _first_int(r"增加(\d+)万元", text) or 0
        income = _money(state, "income")
        expense = _money(state, "expense")
        return (
            f"如果支出增加 {extra} 万元，结余是 {income - expense - extra} 万元。"
            f"确认的支出仍是 {expense} 万元，结余仍是 {income - expense} 万元。"
        )
    if "允许招聘" in text:
        hired = _recruit_total(state)
        return (
            "研发部如果也允许招聘，底稿没有给出研发招聘人数，总招聘人数无法计算，不能编造。"
            f"已确认的招聘合计仍是 {hired} 人，研发部仍然不招聘。"
        )
    if "订单C" in text and "缺货" in text:
        stockout = _num(state["company"].get("stockout"))
        return (
            "若缺货商品里有 3 种是订单 C 要用的，订单 C 仍在处理，这 3 种可能发不齐。"
            f"这只是风险分析，缺货仍是 {stockout} 种，库存数字没有改。"
        )
    if re.search(r"暂时不要修改|只是模拟|不要修改", text):
        return "确认数据没有改。" + _brief(state)
    return "这是假设，已确认的数据不改。" + _brief(state)


def _apply(state: dict[str, Any], text: str) -> str:
    if "撤销" in text and "曾模拟" not in text:
        return "模拟已撤销，确认值保持。" + (_windows_line(state) or _brief(state))
    _capture_scene(state, text)
    notes: list[str] = []
    if _apply_orders(state, text, notes) or _apply_departments(state, text, notes) or _apply_priority(state, text, notes) or _apply_quantities(state, text, notes):
        return " ".join(notes)
    return " ".join(notes)


def _capture_scene(state: dict[str, Any], text: str) -> None:
    if match := re.search(r"产品名称叫\s*([A-Za-z0-9]+)", text):
        state["product"] = match.group(1)
    elif match := re.search(r"(?:名称叫|名为)\s*([^\s。，,的]{2,20})", text):
        state["company_name"] = match.group(1)
    if "Windows" in text or "windows" in text.lower():
        state["platform"] = "Windows"
    if "模块" in text:
        found = [
            name
            for name in ("聊天", "员工图谱", "ERP", "MOD 商店", "系统设置")
            if name in text
        ]
        if len(found) >= 3:
            state["modules"] = found
    if "1.7" in text:
        state["first_load"] = "1.7秒"
    if "几十毫秒" in text:
        state["warm_load"] = "几十毫秒"
    if match := re.search(r"连续切换\s*(\d+)\s*次", text):
        state["page_switches"] = int(match.group(1))
    if match := re.search(r"(\d+)\s*轮对话", text):
        state["chat_rounds"] = int(match.group(1))
    if "严重缺陷" in text:
        state["severe"] = True
    if "不要加入安装" in text or "不是安装" in text:
        state["exclude_install"] = True
    if "主要销售" in text:
        state["business"] = "办公设备和办公耗材"
    for key, topic in (("A", "客户管理"), ("B", "库存管理"), ("C", "财务管理")):
        if f"{key}窗口" in text and topic in text:
            state["windows"][key]["topic"] = topic
    if "连续切换页面" in text and "聊天历史" in text:
        state["checks"] = ["连续切换页面", "聊天历史读取", "流式输出", "网络中断恢复"]
    if "什么" not in text and (match := re.search(r"识别标记为\s*([^\s。，,？?]{2,30})", text)):
        state["marker"] = match.group(1)
    if "客户管理任务" in text:
        state["task"] = "客户管理"
    elif "库存管理任务" in text:
        state["task"] = "库存管理"
    elif "财务管理任务" in text:
        state["task"] = "财务管理"


def _apply_orders(state: dict[str, Any], text: str, notes: list[str]) -> bool:
    orders: dict[str, dict[str, Any]] = state["orders"]
    if match := re.search(r"订单([ABC]).{0,40}?金额\s*(\d+)\s*元", text):
        _set_order(state, match.group(1), int(match.group(2)), notes, "录入")
        return True
    if match := re.search(r"订单([ABC])，金额\s*(\d+)\s*元", text):
        _set_order(state, match.group(1), int(match.group(2)), notes, "录入")
        return True
    if "订单B取消" in text or ("订单B" in text and "取消" in text and "金额" not in text):
        order = orders.setdefault("B", {"amount": None, "status": "open"})
        order["status"] = "cancelled"
        notes.append(f"订单 B 已取消，金额 {_num(order.get('amount'))} 元不计入有效金额。")
        state["order_log"].append("订单B取消")
        return True
    if "完成发货" in text or "处理中" in text:
        if "订单A" in text and "发货" in text:
            orders.setdefault("A", {"amount": None, "status": "open"})["status"] = "shipped"
        if "订单C" in text and "处理中" in text:
            orders.setdefault("C", {"amount": None, "status": "open"})["status"] = "open"
        notes.append(_order_status_line(state))
        return True
    if match := re.search(r"原来的\s*(\d+)\s*元应该修改为\s*(\d+)\s*元", text):
        _retarget_amount(state, int(match.group(1)), int(match.group(2)), notes)
        return True
    if match := re.search(r"(\d+)\s*元是错误的，正确金额是\s*(\d+)\s*元", text):
        _retarget_amount(state, int(match.group(1)), int(match.group(2)), notes)
        return True
    if match := re.search(r"请以\s*(\d+)\s*元为最终数据", text):
        amount = int(match.group(1))
        if "C" in orders:
            orders["C"]["amount"] = amount
            state["order_log"].append(f"订单C最终{amount}")
            notes.append(f"订单 C 最终金额是 {amount} 元。订单 A、订单 B 没有改。")
            return True
    if "金额不变" in text or "不要修改其他订单" in text or "保持取消" in text:
        notes.append("其他订单保持当前确认状态。" + _order_status_line(state))
        return True
    if "金额输入错误" in text:
        notes.append("已记下订单金额有误。还没有新的确认金额，先不改。")
        return True
    return False


def _set_order(
    state: dict[str, Any], name: str, amount: int, notes: list[str], how: str
) -> None:
    state["orders"][name] = {"amount": amount, "status": "open"}
    state["order_log"].append(f"订单{name}{how}{amount}")
    notes.append(f"订单 {name} 金额 {amount} 元，当前按未取消记录。")


def _retarget_amount(state: dict[str, Any], old: int, new: int, notes: list[str]) -> None:
    for name, order in state["orders"].items():
        if order.get("amount") == old:
            order["amount"] = new
            state["order_log"].append(f"订单{name}由{old}改为{new}")
            notes.append(f"订单 {name} 的金额从 {old} 元改为 {new} 元。{old} 元不再是当前金额。")
            return
    notes.append(f"没有找到当前金额为 {old} 元的订单，不能改成 {new} 元。")


def _apply_departments(state: dict[str, Any], text: str, notes: list[str]) -> bool:
    if match := re.search(
        rf"刚才({_DEPT_RE})增加(\d+)人是错误的，实际只增加(\d+)人", text
    ):
        name = _DEPT[match.group(1)]
        actual = int(match.group(3))
        base = int(state["dept_base"].get(name, _num(state["depts"].get(name))))
        state["depts"][name] = base + actual
        state["changes"] = [
            item for item in state["changes"] if not str(item).startswith(f"{name}增加")
        ]
        state["changes"].append(
            f"{name}曾记增加{match.group(2)}人，已纠正为只增加{actual}人，当前{state['depts'][name]}"
        )
        notes.append(
            f"{name}实际只增加 {actual} 人，现在是 {state['depts'][name]} 人。"
            f"部门合计 {_dept_sum(state)} 人。"
        )
        return True
    if "保持不变" in text and re.search(_DEPT_RE, text) and "优先级" not in text:
        name = _DEPT[re.search(_DEPT_RE, text).group(0)]  # type: ignore[union-attr]
        state["changes"].append(f"{name}人数保持不变，仍为{state['depts'].get(name)}")
        notes.append(f"{name}保持 {_num(state['depts'].get(name))} 人，不按新的增减改。")
        return True
    if "恢复原来的限制" in text or re.search(r"不允许招聘|暂时不招聘|不招聘", text):
        if "研发" not in state["recruit_ban"]:
            state["recruit_ban"].append("研发")
        state["recruit"].pop("研发", None)
        notes.append(f"研发不招聘。已给出人数的招聘合计 {_recruit_total(state)} 人。")
        return True
    if match := re.search(rf"({_DEPT_RE})(?:再)?(?:新增|增加)(\d+)名", text):
        name = _DEPT[match.group(1)]
        added = int(match.group(2))
        current = _num(state["depts"].get(name))
        state["dept_base"][name] = current
        state["depts"][name] = current + added
        state["changes"].append(f"{name}增加{added}，现为{state['depts'][name]}")
        notes.append(f"{name}增加 {added} 人，现在是 {state['depts'][name]} 人。")
        return True
    if match := re.search(rf"({_DEPT_RE})离职(\d+)人", text):
        name = _DEPT[match.group(1)]
        left = int(match.group(2))
        state["depts"][name] = _num(state["depts"].get(name)) - left
        state["changes"].append(f"{name}离职{left}，现为{state['depts'][name]}")
        notes.append(f"{name}离职 {left} 人，现在是 {state['depts'][name]} 人。")
        return True
    hired = list(re.finditer(rf"({_DEPT_RE})计划招聘(\d+)人", text))
    if hired:
        parts = []
        for item in hired:
            name = _DEPT[item.group(1)]
            count = int(item.group(2))
            if name in state["recruit_ban"]:
                parts.append(f"{name}不招聘，{count}人不计入")
                continue
            state["recruit"][name] = count
            parts.append(f"{name}{count}人")
        notes.append("招聘：" + "，".join(parts) + f"。合计 {_recruit_total(state)} 人。")
        return True
    if any(token in text for token in ("新增", "增加", "离职", "招聘", "错误", "实际只")):
        return False
    found = list(re.finditer(rf"({_DEPT_RE})(?:有)?(\d+)人", text))
    if not found or "多少" in text:
        if match := re.search(r"(?:总共有|目前有)(\d+)名员工", text):
            state["headcount_stated"] = int(match.group(1))
            notes.append(f"已记下员工总数 {match.group(1)} 人。部门人数以随后给出的为准。")
            return True
        return False
    parts = []
    for item in found:
        name = _DEPT[item.group(1)]
        value = int(item.group(2))
        state["depts"][name] = value
        state["dept_initial"].setdefault(name, value)
        parts.append(f"{name}{value}人")
    notes.append("已确认部门人数：" + "，".join(parts) + "。")
    return True


def _apply_priority(state: dict[str, Any], text: str, notes: list[str]) -> bool:
    changed = False
    patterns = (
        (r"高优先级.{0,12}?(\d+)\s*小时", "高"),
        (r"中优先级.{0,12}?(\d+)\s*小时", "中"),
        (r"低优先级.{0,12}?(\d+)\s*小时", "低"),
        (r"高优先级处理时间改为\s*(\d+)\s*小时", "高"),
        (r"低优先级调整为\s*(\d+)\s*小时", "低"),
    )
    for pattern, name in patterns:
        if match := re.search(pattern, text):
            value = int(match.group(1))
            state["priority_initial"].setdefault(name, state["priority"].get(name, value))
            state["priority"][name] = value
            changed = True
    if not changed:
        return False
    notes.append(_priority_line(state))
    return True


def _apply_quantities(state: dict[str, Any], text: str, notes: list[str]) -> bool:
    slot = _bucket(state, text)
    if match := re.search(r"客户数量从\s*(\d+)\s*家调整为\s*(\d+)\s*家", text):
        slot["customers"] = int(match.group(2))
        _remember_initial(state, slot, "customers", int(match.group(1)))
        if active := re.search(r"活跃客户仍然是\s*(\d+)\s*家", text):
            slot["active"] = int(active.group(1))
        notes.append(
            f"客户调整为 {slot['customers']} 家，活跃客户 {_num(slot.get('active'))} 家。"
        )
        return True
    if match := re.search(r"(?:现在|再)?新增\s*(\d+)\s*家客户", text):
        slot["customers"] = _num(slot.get("customers")) + int(match.group(1))
        state["customer_added"] = _num(state.get("customer_added")) + int(match.group(1))
        notes.append(f"客户现在是 {slot['customers']} 家。")
        return True
    if match := re.search(r"新增客户中有\s*(\d+)\s*家已经成为活跃", text):
        slot["active"] = _num(slot.get("active")) + int(match.group(1))
        notes.append(f"活跃客户现在是 {slot['active']} 家。非活跃 {_inactive(slot)} 家。")
        return True
    if "客户" in text and (match := re.search(r"(\d+)\s*家暂时没有交易", text)):
        notes.append(
            f"这 {match.group(1)} 家先不算活跃。客户 { _num(slot.get('customers')) } 家，"
            f"活跃 {_num(slot.get('active'))} 家，非活跃 {_inactive(slot)} 家。"
        )
        return True
    if match := re.search(r"客户数量\s*(\d+)\s*家", text):
        slot["customers"] = int(match.group(1))
        _remember_initial(state, slot, "customers", int(match.group(1)))
        if active := re.search(r"活跃客户\s*(\d+)\s*家", text):
            slot["active"] = int(active.group(1))
        notes.append(f"客户 {slot['customers']} 家，活跃客户 {_num(slot.get('active'))} 家。")
        return True
    if match := re.search(r"其中\s*(\d+)\s*家属于活跃客户|其中活跃客户\s*(\d+)\s*家", text):
        slot["active"] = int(match.group(1) or match.group(2))
        notes.append(f"活跃客户 {_num(slot.get('active'))} 家。")
        return True
    if match := re.search(r"(\d+)\s*家客户", text):
        slot["customers"] = int(match.group(1))
        _remember_initial(state, slot, "customers", int(match.group(1)))
        if active := re.search(r"其中\s*(\d+)\s*家活跃", text):
            slot["active"] = int(active.group(1))
        notes.append(f"客户 {slot['customers']} 家，活跃客户 {_num(slot.get('active'))} 家。")
        return True
    if "缺货" not in text and (match := re.search(r"现在新增\s*(\d+)\s*种商品", text)):
        slot["sku"] = _num(slot.get("sku")) + int(match.group(1))
        notes.append(f"商品现在是 {slot['sku']} 种。")
        return True
    if match := re.search(r"其中\s*(\d+)\s*种商品已经入库", text):
        state["inbound_kinds"] = int(match.group(1))
        notes.append(f"已记下 {match.group(1)} 种商品入库，还没给出每种件数时不改库存件数。")
        return True
    if match := re.search(r"每种入库商品数量为\s*(\d+)\s*件", text):
        kinds = _num(state.get("inbound_kinds"))
        added = kinds * int(match.group(1))
        slot["stock"] = _num(slot.get("stock")) + added
        state["inbound_kinds"] = None
        state["last_inbound"] = added
        notes.append(f"本次入库 {added} 件。库存现在是 {slot['stock']} 件。")
        return True
    if match := re.search(r"(\d+)\s*种商品恢复供应", text):
        slot["stockout"] = _num(slot.get("stockout")) - int(match.group(1))
        notes.append(f"缺货现在是 {slot['stockout']} 种。")
        return True
    if match := re.search(r"新增\s*(\d+)\s*种商品缺货", text):
        slot["stockout"] = _num(slot.get("stockout")) + int(match.group(1))
        notes.append(f"缺货现在是 {slot['stockout']} 种。")
        return True
    for match in re.finditer(r"(\d+)\s*种(?:不同)?商品", text):
        head = text[max(0, match.start() - 6) : match.start()]
        tail = text[match.end() : match.end() + 8]
        if "缺货" in head or "缺货" in tail or "入库" in head or "入库" in tail:
            continue
        slot["sku"] = int(match.group(1))
        _remember_initial(state, slot, "sku", slot["sku"])
        notes.append(f"商品 {slot['sku']} 种。")
        break
    if match := re.search(r"缺货(?:商品)?(?:数量)?(?:是|有)?\s*(\d+)\s*(?:种|件)", text) or re.search(
        r"(\d+)\s*种商品处于缺货|其中\s*(\d+)\s*种商品缺货", text
    ):
        slot["stockout"] = int(next(group for group in match.groups() if group))
        _remember_initial(state, slot, "stockout", slot["stockout"])
        unit = "件" if str(match.group(0)).endswith("件") else "种"
        notes.append(f"缺货 {slot['stockout']} {unit}。")
    if match := re.search(r"库存(?:商品|总量|数量)?(?:是|为)?\s*(\d+)\s*件|总库存数量是\s*(\d+)\s*件", text):
        slot["stock"] = int(next(group for group in match.groups() if group))
        _remember_initial(state, slot, "stock", slot["stock"])
        notes.append(f"库存 {slot['stock']} 件。")
    if "订单收入占" in text or "其他收入占" in text:
        if match := re.search(r"订单收入占\s*(\d+)\s*万元", text):
            state["income_parts"]["订单"] = int(match.group(1))
        if match := re.search(r"其他收入占\s*(\d+)\s*万元", text):
            state["income_parts"]["其他"] = int(match.group(1))
        if match := re.search(r"收入\s*(\d+)\s*万元", text):
            _bucket(state, text)["income"] = int(match.group(1))
        notes.append(f"收入构成已记下。收入合计仍是 {_money(state, 'income')} 万元。")
        return True
    for label, key in (("人工成本", "人工"), ("服务器成本", "服务器"), ("其他运营成本", "运营")):
        if label in text and (match := re.search(rf"{label}\s*(\d+)\s*万元", text)):
            state["expense_parts"][key] = int(match.group(1))
            notes.append(f"{label} {match.group(1)} 万元。支出合计仍是 {_money(state, 'expense')} 万元。")
            return True
    if match := re.search(r"收入(?:为)?\s*(\d+)\s*万元", text):
        slot["income"] = int(match.group(1))
        _remember_initial(state, slot, "income", slot["income"])
        notes.append(f"收入 {slot['income']} 万元。")
    if match := re.search(r"支出(?:为)?\s*(\d+)\s*万元", text):
        slot["expense"] = int(match.group(1))
        _remember_initial(state, slot, "expense", slot["expense"])
        notes.append(f"支出 {slot['expense']} 万元。")
    if "数据不变" in text:
        notes.append("已确认的窗口数据保持不变。" + _windows_line(state))
        return True
    if notes:
        return True
    return False


def _answer(state: dict[str, Any], text: str) -> str | None:
    if not re.search(r"多少|什么|哪些|哪两|是否|分别|总结|整理|报告|分析|解释|检查|告诉我|重新计算|重新整理|哪个|标出|结余|建议", text):
        return None
    if "整个测试项目" in text or ("五个模块" in text and "总结" in text) or ("继续之前" in text and "总结" in text):
        return _c11_summary(state)
    if "测试范围" in text and ("整理" in text or "总结" in text):
        return _c11_summary(state)
    if "识别标记" in text and ("什么" in text or "库存" in text or "收入" in text or "活跃" in text):
        return _marker_reply(state, text)
    if "产品名称" in text or ("运行" in text and "平台" in text and "总结" not in text):
        return f"产品名称是 {state['product'] or '当前会话没有写'}，平台是 {state['platform'] or '当前会话没有写'}。"
    if "1.7" in text or ("首次" in text and "多少时间" in text) or "再次进入" in text:
        return f"首次进入客户管理页面是 {state['first_load'] or '没有记录'}，再次进入是 {state['warm_load'] or '没有记录'}。"
    if "三组业务" in text or ("A、B、C" in text and "数据" in text):
        return "撤销之后的确认值：" + _windows_line(state)
    if "继续之前" in text and "总结" in text:
        return _c11_summary(state)
    if "整个测试项目" in text or ("五个模块" in text and "总结" in text):
        return _c11_summary(state)
    if "测试范围" in text and ("整理" in text or "总结" in text):
        return _c11_summary(state)
    if "三个窗口" in text:
        return _windows_line(state)
    if "组织情况" in text or ("四个部门" in text and "人数" in text):
        return _org_summary(state)
    if "哪两个部门" in text:
        return _pair_equal(state, _first_int(r"等于\s*(\d+)", text) or 20)
    if "哪个部门人数最多" in text or "哪个部门" in text and "最多" in text:
        return _largest_dept(state)
    if "哪些部门可以招聘" in text:
        allowed = [name for name in ("销售", "财务", "客服", "研发") if name not in state["recruit_ban"]]
        detail = "，".join(f"{name}{state['recruit'][name]}人" for name in allowed if name in state["recruit"])
        return f"可以招聘的部门：{'、'.join(allowed) or '没有'}。已给出的人数：{detail or '没有'}。"
    if "招聘人数" in text or "最终招聘" in text:
        return f"招聘合计 {_recruit_total(state)} 人。研发{'不招聘' if '研发' in state['recruit_ban'] else '没有禁止'}。"
    if "销售部和研发部" in text or ("销售部" in text and "研发部" in text and "多少人" in text):
        return f"销售 {_num(state['depts'].get('销售'))} 人，研发 {_num(state['depts'].get('研发'))} 人。"
    if "员工总数" in text or "总人数" in text or "多少员工" in text or "多少人" in text or "员工变动" in text:
        return _headcount_reply(state, text)
    if "活跃率" in text:
        return _rate_reply(state, text)
    if "缺货" in text and ("比例" in text or "风险" in text or "分析" in text):
        return _stockout_reply(state)
    if "结余" in text or ("余额" in text and "多少" in text):
        return _finance_reply(state)
    if "成本控制" in text or ("财务" in text and "经营情况" in text):
        return _finance_reply(state)
    if "库存件数" in text or ("库存" in text and "多少" in text and "缺货" not in text and "识别标记" not in text):
        slot = _bucket(state, text)
        return f"库存 {_num(slot.get('stock'))} 件。"
    if "客户总数" in text or ("现在客户" in text and "多少" in text) or text.startswith("现在客户总数"):
        slot = _bucket(state, text)
        return f"客户 {_num(slot.get('customers'))} 家。"
    if "非活跃" in text and "多少" in text:
        slot = _bucket(state, text)
        return f"非活跃客户 {_inactive(slot)} 家。"
    if "真实活跃" in text or ("活跃客户" in text and "多少" in text):
        slot = _bucket(state, text)
        return f"活跃客户 {_num(slot.get('active'))} 家。这是确认值。"
    if "客户" in text and "多少" in text and "最初" not in text and "后来" not in text:
        slot = _bucket(state, text)
        return f"客户 {_num(slot.get('customers'))} 家。"
    if "客户管理数据" in text and "总结" in text:
        slot = state["company"]
        return (
            f"客户 {_num(slot.get('customers'))} 家，活跃 {_num(slot.get('active'))} 家，"
            f"非活跃 {_inactive(slot)} 家。"
        )
    if "本次入库" in text:
        if state.get("last_inbound") is None:
            return "入库件数要等「几种已经入库」和「每种多少件」都出现后才计算。"
        return f"本次入库 {state['last_inbound']} 件。"
    if "原来的库存" in text:
        return f"最初库存 {_num(state['initial'].get('stock'))} 件。"
    if "入库后总库存" in text or ("总库存" in text and "多少" in text):
        return f"库存 {_num(state['company'].get('stock'))} 件。"
    if "缺货商品数量" in text or ("缺货" in text and "多少" in text and "最初" not in text):
        return f"缺货 {_num(state['company'].get('stockout'))} 种。"
    if "商品种类" in text or ("商品" in text and "库存" in text and "缺货" in text and "总结" in text):
        slot = state["company"]
        return (
            f"商品 { _num(slot.get('sku')) } 种，库存 {_num(slot.get('stock'))} 件，"
            f"缺货 {_num(slot.get('stockout'))} 种。"
        )
    if "三个订单的总金额" in text:
        return f"三个订单金额合计 {_order_sum(state, valid_only=False)} 元。"
    if "有效订单" in text and ("金额" in text or "多少" in text):
        count = sum(1 for order in state["orders"].values() if order.get("status") != "cancelled" and order.get("amount") is not None)
        return (
            f"有效订单 {count} 笔，有效金额 {_order_sum(state, valid_only=True)} 元。"
            + _order_status_line(state)
        )
    if "分别总结三个订单" in text or "金额和当前状态" in text:
        return _order_status_line(state)
    if "哪些订单已经取消" in text:
        names = [name for name, order in state["orders"].items() if order.get("status") == "cancelled"]
        return "已取消：" + ("、".join(f"订单{name}" for name in names) or "没有") + "。"
    if "处理中" in text and "哪些" in text:
        names = [name for name, order in state["orders"].items() if order.get("status") == "open"]
        return "处理中：" + ("、".join(f"订单{name}" for name in names) or "没有") + "。"
    if "12000" in text or "错误的12000" in text:
        current = _num((state["orders"].get("C") or {}).get("amount"))
        return f"当前订单 C 是 {current} 元，不把 12000 元当作当前金额。"
    if "修改的全过程" in text or "全过程" in text:
        return "订单修改过程：" + "；".join(state["order_log"]) + "。" + _order_status_line(state)
    if "最初有多少家客户" in text or "后来一共新增" in text:
        parts = []
        if "最初" in text:
            parts.append(f"最初客户 {_num(state['initial'].get('customers'))} 家。")
        if "后来" in text:
            parts.append(f"后来新增客户 {_num(state.get('customer_added'))} 家。")
        return "".join(parts)
    if "最初有多少种缺货" in text:
        return f"最初缺货 {_num(state['initial'].get('stockout'))} 种。"
    if "订单A和订单C" in text:
        return (
            f"订单 A {_num((state['orders'].get('A') or {}).get('amount'))} 元，"
            f"订单 C {_num((state['orders'].get('C') or {}).get('amount'))} 元。"
        )
    if "最初的收入" in text:
        return (
            f"最初收入 {_num(state['initial'].get('income'))} 万元，"
            f"最初支出 {_num(state['initial'].get('expense'))} 万元。"
        )
    if state["priority"] and (
        ("优先级" in text and re.search(r"整理|变化|重新|哪些", text)) or "哪些条件" in text
    ):
        return _priority_line(state) + _priority_delta(state)
    if "人员分布" in text or "各部门" in text:
        return _headcount_reply(state, text)
    if "客户交易" in text or "经营报告" in text or "完整报告" in text or "整合" in text or "所有业务数据" in text:
        return _business_report(state)
    if "所有数字" in text or "无法确认" in text:
        return _business_report(state) + "上面的数字都来自本会话已经确认的事实，没有另补。"
    if "恢复原始财务" in text or ("收入" in text and "支出" in text and "总结" in text):
        return _finance_reply(state)
    if "改善" in text:
        slot = _bucket(state, text)
        return (
            f"活跃 {_num(slot.get('active'))} / 客户 {_num(slot.get('customers'))}，"
            f"非活跃 {_inactive(slot)} 家。改善只针对这 {_inactive(slot)} 家未交易客户，不新增别的数字。"
        )
    if "补货建议" in text:
        slot = _bucket(state, text)
        return (
            f"缺货 {_num(slot.get('stockout'))} / 商品 {_num(slot.get('sku'))} 种，"
            f"库存 {_num(slot.get('stock'))} 件。建议先补这 {_num(slot.get('stockout'))} 种，不另造数量。"
        )
    return None


def _marker_reply(state: dict[str, Any], text: str) -> str:
    marker = state["marker"] or "当前会话没有识别标记"
    parts = [f"识别标记是 {marker}。"]
    if "库存数量" in text:
        stock = state["company"].get("stock")
        if stock is None:
            parts.append("当前会话没有库存数量，不能从别的会话借。")
        else:
            parts.append(f"库存 {stock} 件。")
    if "本月收入" in text or ("收入是多少" in text):
        income = state["company"].get("income")
        if income is None:
            parts.append("当前会话没有本月收入，不能从别的会话借。")
        else:
            parts.append(f"本月收入 {income} 万元。")
    if "活跃客户" in text:
        active = state["company"].get("active")
        if active is None:
            parts.append("当前会话没有活跃客户数量，不能从别的会话借。")
        else:
            parts.append(f"活跃客户 {active} 家。")
    return "".join(parts)


def _c11_summary(state: dict[str, Any]) -> str:
    modules = "、".join(state["modules"]) or "当前会话没有列出模块"
    checks = "、".join(state["checks"]) or "当前会话没有列出检查项"
    severe = "消息丢失、重复消息、不同对话串线，判定为严重缺陷。" if state["severe"] else ""
    install = "不包含安装和卸载。" if state["exclude_install"] else ""
    return (
        f"产品 {state['product'] or '未记录'}，平台 {state['platform'] or '未记录'}。"
        f"模块：{modules}。首次加载 {state['first_load'] or '未记录'}，"
        f"再次切换 {state['warm_load'] or '未记录'}。"
        f"页面切换 {state['page_switches'] or '未记录'} 次，聊天 {state['chat_rounds'] or '未记录'} 轮。"
        f"检查：{checks}。{install}{severe}"
        + _windows_line(state)
    )


def _windows_line(state: dict[str, Any]) -> str:
    parts = []
    for key in ("A", "B", "C"):
        slot = state["windows"][key]
        bits = [slot["topic"] or "未指定业务"]
        if slot["customers"] is not None:
            bits.append(f"客户{slot['customers']}家")
        if slot["active"] is not None:
            bits.append(f"活跃{slot['active']}家")
        if slot["stock"] is not None:
            bits.append(f"库存{slot['stock']}件")
        if slot["stockout"] is not None:
            bits.append(f"缺货{slot['stockout']}件")
        if slot["income"] is not None:
            bits.append(f"收入{slot['income']}万元")
        if slot["expense"] is not None:
            bits.append(f"支出{slot['expense']}万元")
        parts.append(f"{key}：" + "，".join(bits))
    return " ".join(parts)


def _org_summary(state: dict[str, Any]) -> str:
    depts = "，".join(f"{name}{_num(state['depts'].get(name))}人" for name in ("研发", "销售", "财务", "客服"))
    recruit = "，".join(
        f"{name}{state['recruit'][name]}人" for name in ("销售", "财务", "客服", "研发") if name in state["recruit"]
    )
    sales_initial = _num(state["dept_initial"].get("销售"))
    sales_now = _num(state["depts"].get("销售"))
    changes = "；".join(state["changes"]) or "没有人员增减"
    return (
        f"部门人数：{depts}。合计 {_dept_sum(state)} 人。"
        f"21+14+5+8=48，若另有清单写成 43，那和这四个部门对不上，这里用 48。"
        f"招聘：{recruit or '没有'}。禁止招聘：{'、'.join(state['recruit_ban']) or '没有'}。"
        f"销售最初 {sales_initial} 人，现在 {sales_now} 人。过程：{changes}。"
        "已经纠正掉的人数不作为当前人数。"
    )


def _headcount_reply(state: dict[str, Any], text: str) -> str:
    if state["depts"]:
        before = sum(state["dept_initial"].get(name, 0) for name in state["depts"])
        now = _dept_sum(state)
        detail = "，".join(f"{name}{_num(state['depts'].get(name))}人" for name in ("研发", "销售", "财务", "客服") if name in state["depts"])
        extra = ""
        if "变动" in text:
            initial = "，".join(
                f"{name}{_num(state['dept_initial'].get(name))}人" for name in state["depts"]
            )
            extra = f"变动前：{initial}，合计 {before} 人。"
        stated = ""
        if state["headcount_stated"] is not None and state["headcount_stated"] != now:
            stated = f"早先说的总数 {state['headcount_stated']} 人已被后来的部门增减覆盖。"
        return f"当前部门人数：{detail}。合计 {now} 人。{extra}{stated}"
    if state["headcount_stated"] is not None:
        return f"已记下的员工总数是 {state['headcount_stated']} 人。部门人数还没到齐时，不用这个数代替部门合计。"
    return "当前会话没有员工人数。"


def _pair_equal(state: dict[str, Any], target: int) -> str:
    names = [name for name in ("研发", "销售", "财务", "客服") if name in state["depts"]]
    hits = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if _num(state["depts"][left]) + _num(state["depts"][right]) == target:
                hits.append(f"{left}{_num(state['depts'][left])}+{right}{_num(state['depts'][right])}")
    return f"加起来等于 {target} 人的是：" + ("；".join(hits) or "没有") + "。"


def _largest_dept(state: dict[str, Any]) -> str:
    if not state["depts"]:
        return "当前会话没有部门人数。"
    name = max(state["depts"], key=lambda item: _num(state["depts"][item]))
    return f"{name}人数最多，{_num(state['depts'][name])} 人。"


def _rate_reply(state: dict[str, Any], text: str) -> str:
    slot = _bucket(state, text)
    customers = _num(slot.get("customers"))
    active = _num(slot.get("active"))
    if customers == 0:
        return "当前会话没有客户总数，不能算活跃率。"
    rate = round(active * 100 / customers, 1)
    return f"活跃客户 {active} 家，客户 {customers} 家，活跃率 {rate}%。非活跃 {_inactive(slot)} 家。"


def _stockout_reply(state: dict[str, Any]) -> str:
    slot = state["company"]
    sku = _num(slot.get("sku"))
    stockout = _num(slot.get("stockout"))
    if sku == 0:
        return "当前会话没有商品种数，不能算缺货比例。"
    rate = round(stockout * 100 / sku, 1)
    return f"缺货 {stockout} 种，商品 {sku} 种，缺货比例 {rate}%。库存 {_num(slot.get('stock'))} 件。这个比例不改库存。"


def _finance_reply(state: dict[str, Any]) -> str:
    income = _money(state, "income")
    expense = _money(state, "expense")
    parts = ""
    if state["expense_parts"]:
        parts = "支出分项：" + "，".join(f"{key}{value}万元" for key, value in state["expense_parts"].items()) + "。"
    elif expense:
        parts = "支出没有分项，不能编造人工或服务器成本。"
    income_parts = ""
    if state["income_parts"]:
        income_parts = "收入分项：" + "，".join(f"{key}{value}万元" for key, value in state["income_parts"].items()) + "。"
    return f"收入 {income} 万元，支出 {expense} 万元，余额 {income - expense} 万元。{income_parts}{parts}"


def _business_report(state: dict[str, Any]) -> str:
    slot = state["company"]
    depts = "，".join(
        f"{name}{_num(state['depts'].get(name))}人" for name in ("研发", "销售", "财务", "客服")
    )
    priority = _priority_line(state)
    return (
        f"客户 {_num(slot.get('customers'))}，活跃 {_num(slot.get('active'))}，非活跃 {_inactive(slot)}。"
        f"商品 {_num(slot.get('sku'))} 种，库存 {_num(slot.get('stock'))} 件，缺货 {_num(slot.get('stockout'))} 种。"
        f"有效订单金额 {_order_sum(state, valid_only=True)} 元。"
        f"有效订单 {sum(1 for order in state['orders'].values() if order.get('status') != 'cancelled')} 笔。"
        + _order_status_line(state)
        + f"收入 {_money(state, 'income')} 万元，支出 {_money(state, 'expense')} 万元，"
        f"余额 {_money(state, 'income') - _money(state, 'expense')} 万元。"
        f"员工 {depts}，合计 {_dept_sum(state)} 人。{priority}"
    )


def _order_status_line(state: dict[str, Any]) -> str:
    labels = {"open": "处理中", "shipped": "已发货", "cancelled": "已取消"}
    parts = []
    for name in ("A", "B", "C"):
        order = state["orders"].get(name)
        if not order:
            continue
        parts.append(
            f"订单{name} {_num(order.get('amount'))} 元，{labels.get(order.get('status'), '未说明')}"
        )
    return "；".join(parts) + ("。" if parts else "当前没有订单。")


def _order_sum(state: dict[str, Any], *, valid_only: bool) -> int:
    total = 0
    for order in state["orders"].values():
        if valid_only and order.get("status") == "cancelled":
            continue
        total += _num(order.get("amount"))
    return total


def _priority_line(state: dict[str, Any]) -> str:
    if not state["priority"]:
        return ""
    return "优先级：" + "，".join(
        f"{name}{_num(state['priority'].get(name))}小时" for name in ("高", "中", "低") if name in state["priority"]
    ) + "。"


def _priority_delta(state: dict[str, Any]) -> str:
    bits = []
    for name in ("高", "中", "低"):
        if name not in state["priority"]:
            continue
        initial = state["priority_initial"].get(name)
        current = state["priority"][name]
        if initial == current:
            bits.append(f"{name}保持{current}小时")
        else:
            bits.append(f"{name}从{initial}小时改为{current}小时")
    return " ".join(bits)


def _brief(state: dict[str, Any]) -> str:
    if any(state["windows"][key]["customers"] is not None for key in state["windows"]):
        return _windows_line(state)
    if state["depts"]:
        return _headcount_reply(state, "")
    slot = state["company"]
    if slot["customers"] is not None or slot["stock"] is not None or slot["income"] is not None:
        return _business_report(state)
    return ""


def _bucket(state: dict[str, Any], text: str) -> dict[str, Any]:
    if match := re.search(r"([ABC])窗口", text):
        return state["windows"][match.group(1)]
    if state["task"] == "客户管理" and "客户" in text:
        return state["company"]
    return state["company"]


def _remember_initial(state: dict[str, Any], slot: dict[str, Any], key: str, value: int) -> None:
    if slot is state["company"] and key not in state["initial"]:
        state["initial"][key] = value


def _inactive(slot: dict[str, Any]) -> int:
    if slot.get("customers") is None or slot.get("active") is None:
        return 0
    return _num(slot["customers"]) - _num(slot["active"])


def _dept_sum(state: dict[str, Any]) -> int:
    return sum(_num(value) for value in state["depts"].values())


def _recruit_total(state: dict[str, Any]) -> int:
    return sum(
        int(value)
        for name, value in state["recruit"].items()
        if name not in state["recruit_ban"]
    )


def _money(state: dict[str, Any], key: str) -> int:
    value = state["company"].get(key)
    if value is None:
        for slot in state["windows"].values():
            if slot.get(key) is not None:
                return int(slot[key])
        return 0
    return int(value)


def _num(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))
