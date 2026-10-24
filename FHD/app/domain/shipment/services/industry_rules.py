"""行业规则引擎（领域服务）：可插拔、schema 驱动的字段校验与派生计算。

设计要点（行业元体系·规则层）：
- 不写 ``if industry == ...`` 分支。不同行业走不同规则，**纯粹由行业 profile 的
  ``subsystems[menuKey]`` 数据驱动**——字段的 ``validators`` 决定校验、子系统的
  ``rules`` 决定派生计算。涂料与考勤的差异体现在它们各自 manifest 声明的数据里。
- 校验类型与派生算子各自是**注册表**（``VALIDATOR_REGISTRY`` / ``DERIVATION_REGISTRY``），
  新增规则类型 = 往注册表登记一个函数，无需改引擎主体。

数据形状（来自 ``IndustryProfile.subsystems[menuKey]``，见 value_objects_industry.get_current_subsystem_schema）::

    {
      "fields": [
        {"key": "specification", "label": "班次", "validators": [{"type": "oneOf", "params": ["早", "中", "晚"]}]},
        {"key": "expire_date", "label": "保质期", "validators": [{"type": "not_expired"}]},
        {"key": "name", "label": "产品名称", "required": true}
      ],
      "rules": {
        "quantity_kg": {"op": "mul", "args": ["quantity_tins", "tin_spec"]},
        "amount":      {"op": "mul", "args": ["quantity_kg", "unit_price"]}
      }
    }
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Optional

from app.utils.operational_errors import RECOVERABLE_ERRORS


@dataclass
class FieldError:
    """单个字段的规则违反。"""

    field: str
    label: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "label": self.label, "message": self.message}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_number(value: Any) -> float:
    try:
        if _is_empty(value):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Any) -> Optional[date]:
    """宽松解析日期：支持 ISO ``YYYY-MM-DD`` 与含时间的 ISO 串。"""
    if _is_empty(value):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(text).date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 校验类型注册表：type -> fn(value, params) -> error_message | None
# ---------------------------------------------------------------------------
def _validate_one_of(value: Any, params: Any) -> Optional[str]:
    if _is_empty(value):
        return None  # 空值交给 required 处理
    allowed = [str(x) for x in params] if isinstance(params, list) else []
    if not allowed:
        return None
    if str(value) not in allowed:
        return f"必须是 {('、').join(allowed)} 之一"
    return None


def _validate_range(value: Any, params: Any) -> Optional[str]:
    if _is_empty(value):
        return None
    p = params if isinstance(params, dict) else {}
    num = _to_number(value)
    mn, mx = p.get("min"), p.get("max")
    if mn is not None and num < float(mn):
        return f"不能小于 {mn}"
    if mx is not None and num > float(mx):
        return f"不能大于 {mx}"
    return None


def _validate_regex(value: Any, params: Any) -> Optional[str]:
    if _is_empty(value):
        return None
    pattern = params if isinstance(params, str) else (params or {}).get("pattern", "")
    if not pattern:
        return None
    try:
        if re.search(pattern, str(value)) is None:
            return "格式不正确"
    except re.error:
        return None
    return None


def _validate_not_expired(value: Any, params: Any) -> Optional[str]:
    """保质期/到期日不得早于今天（用于涂料批次保质期等）。空值跳过。"""
    d = _parse_date(value)
    if d is None:
        return None
    if d < date.today():
        return "已过保质期（到期日早于今天）"
    return None


VALIDATOR_REGISTRY: dict[str, Callable[[Any, Any], Optional[str]]] = {
    "oneOf": _validate_one_of,
    "range": _validate_range,
    "regex": _validate_regex,
    "not_expired": _validate_not_expired,
}


def register_validator(type_name: str, fn: Callable[[Any, Any], Optional[str]]) -> None:
    """登记一个新的校验类型（供 Mod/扩展插入行业特定校验）。"""
    VALIDATOR_REGISTRY[str(type_name)] = fn


# ---------------------------------------------------------------------------
# 派生算子注册表：op -> fn(list_of_numbers) -> number
# ---------------------------------------------------------------------------
def _op_mul(args: list[float]) -> float:
    out = 1.0
    for a in args:
        out *= a
    return out


def _op_add(args: list[float]) -> float:
    return sum(args)


def _op_sub(args: list[float]) -> float:
    if not args:
        return 0.0
    out = args[0]
    for a in args[1:]:
        out -= a
    return out


DERIVATION_REGISTRY: dict[str, Callable[[list[float]], float]] = {
    "mul": _op_mul,
    "add": _op_add,
    "sub": _op_sub,
}


def register_derivation(op: str, fn: Callable[[list[float]], float]) -> None:
    """登记一个新的派生算子。"""
    DERIVATION_REGISTRY[str(op)] = fn


# ---------------------------------------------------------------------------
# 引擎入口
# ---------------------------------------------------------------------------
def _resolve_schema(menu_key: str, schema: Optional[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(schema, dict):
        return schema
    try:
        from app.domain.value_objects_industry import get_current_subsystem_schema

        s = get_current_subsystem_schema(menu_key)
        return s if isinstance(s, dict) else {}
    except RECOVERABLE_ERRORS:
        return {}


def validate_subsystem_record(
    menu_key: str,
    record: dict[str, Any],
    *,
    schema: Optional[dict[str, Any]] = None,
) -> list[FieldError]:
    """按当前行业该子系统的字段 schema 校验一条记录。

    规则全部来自 schema 数据（required + 各字段 validators），因此涂料/考勤等
    不同行业自然走不同校验，引擎本身无行业分支。``schema`` 可显式传入（便于测试/
    无请求上下文），否则按 ``menu_key`` 从当前行业 profile 读取。
    """
    schema = _resolve_schema(menu_key, schema)
    record = record or {}
    errors: list[FieldError] = []
    for field in schema.get("fields", []) or []:
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        label = str(field.get("label") or key)
        value = record.get(key)

        if field.get("required") and _is_empty(value):
            errors.append(FieldError(key, label, f"{label}不能为空"))
            continue

        for v in field.get("validators", []) or []:
            if not isinstance(v, dict):
                continue
            vtype = str(v.get("type") or "").strip()
            handler = VALIDATOR_REGISTRY.get(vtype)
            if handler is None:
                continue
            try:
                msg = handler(value, v.get("params"))
            except RECOVERABLE_ERRORS:
                msg = None
            if msg:
                errors.append(FieldError(key, label, f"{label}{msg}"))
    return errors


def compute_subsystem_derived(
    menu_key: str,
    record: dict[str, Any],
    *,
    schema: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """按子系统 ``rules`` 计算派生字段，返回更新后的记录副本。

    例：涂料 orders 声明 ``{"quantity_kg": {"op":"mul","args":["quantity_tins","tin_spec"]},
    "amount": {"op":"mul","args":["quantity_kg","unit_price"]}}``，引擎据此算出
    quantity_kg 与 amount；考勤未声明则不计算——差异由数据驱动。
    """
    schema = _resolve_schema(menu_key, schema)
    out = dict(record or {})
    rules = schema.get("rules", {})
    if not isinstance(rules, dict):
        return out
    for target, spec in rules.items():
        if not isinstance(spec, dict):
            continue
        op = str(spec.get("op") or "").strip()
        fn = DERIVATION_REGISTRY.get(op)
        if fn is None:
            continue
        args = spec.get("args", [])
        if not isinstance(args, list):
            continue
        values = [_to_number(out.get(a)) for a in args]
        try:
            out[str(target)] = fn(values)
        except RECOVERABLE_ERRORS:
            continue
    return out


__all__ = [
    "DERIVATION_REGISTRY",
    "FieldError",
    "VALIDATOR_REGISTRY",
    "compute_subsystem_derived",
    "register_derivation",
    "register_validator",
    "validate_subsystem_record",
]
