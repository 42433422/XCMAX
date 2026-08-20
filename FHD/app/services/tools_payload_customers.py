"""Customer legacy tool handlers."""

from __future__ import annotations

import logging

from app.services.tools_payload_dispatch_common import NOT_HANDLED
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def dispatch_customer_tool_payload(
    tool_id,
    action: str,
    params: dict,
    *,
    json_response_fn,
    hdr_getter,
    parse_order_text_fn,
):
    _j = json_response_fn
    _hdr = hdr_getter
    _ = parse_order_text_fn
    if tool_id == "customers":
        # pro 模式下 action 往往是固定的“执行”，但 TaskAgent/前端 params 里会携带真正的子动作（如 search/query）
        effective_action = action
        if (str(action) or "") in ("执行", "exec", "run") and params.get("action"):
            effective_action = str(params.get("action") or "")

        # 不同上游/模型可能不会把自然语言放在 order_text 里，这里把常见字段都拼一下，提升意图识别鲁棒性。
        order_text = (
            params.get("order_text")
            or params.get("text")
            or params.get("message")
            or params.get("content")
            or ""
        ).strip()
        lower_text = order_text.lower()

        # 把 params 的值也一起纳入意图判断（避免 order_text 为空导致误走 search/query redirect）
        param_blob = " ".join([str(v) for v in (params or {}).values() if v is not None]).strip()
        lower_param_blob = param_blob.lower()

        has_add_verb = (
            any(v in order_text for v in ["添加", "新增", "创建", "新建", "增加"])
            or any(v in lower_text for v in ["add", "create", "new"])
            or any(v in param_blob for v in ["添加", "新增", "创建", "新建", "增加"])
            or any(v in lower_param_blob for v in ["add", "create", "new"])
        )
        has_del_verb = (
            any(v in order_text for v in ["删除", "移除", "去掉"])
            or any(v in lower_text for v in ["delete", "remove", "del"])
            or any(v in param_blob for v in ["删除", "移除", "去掉"])
            or any(v in lower_param_blob for v in ["delete", "remove", "del"])
        )

        keyword = (params.get("keyword") or "").strip()
        # 如果是“检索/搜索”但上游没给 keyword，就尽量用 params 里的名称兜底
        # 注意：一旦用户明确表达删除（has_del_verb），删除应当优先覆盖 search/query redirect。
        if (
            effective_action in ("search", "query")
            and not keyword
            and not has_add_verb
            and not has_del_verb
        ):
            keyword = (
                params.get("unit_name") or params.get("name") or params.get("customer_name") or ""
            ).strip()
        # 如果自然语言包含“添加/新增/创建”，即便 AI 把 action 判成 search/query，也应优先创建。
        if (
            effective_action in ("search", "query")
            and keyword
            and not has_add_verb
            and not has_del_verb
        ):
            logger.info("customers: redirect search/query keyword=%s", keyword)
            return _j(
                {
                    "success": True,
                    "redirect": f"/console?view=customers&keyword={keyword}",
                    "message": f"已按关键词检索客户：{keyword}",
                }
            )
        if effective_action == "view" and not has_add_verb and not has_del_verb:
            logger.info("customers: redirect view")
            return _j({"success": True, "redirect": "/console?view=customers"})

        logger.info(
            "customers: attempt create? effective_action=%s has_add_verb=%s order_text_len=%s params_keys=%s",
            effective_action,
            has_add_verb,
            len(order_text or ""),
            list(params.keys()),
        )

        # 聊天/工具侧删除：支持 action=delete/remove/del，幂等删除（不存在也返回 success）
        if effective_action in ("delete", "remove", "del") or has_del_verb:
            from app.db.models import PurchaseUnit
            from app.services.unified_query_service import query_service

            target_id = params.get("customer_id") or params.get("id") or params.get("unit_id")
            target_name = (
                params.get("customer_name") or params.get("unit_name") or params.get("name") or ""
            ).strip()

            # 尽量从自然语言中提取名称：如“删除客户/购买单位叫XX”
            if not target_name and order_text:
                import re

                # 支持：包含“联系人/电话/地址”后缀的删除句式
                # 例：删除购买单位小王公司联系人王总  -> 提取“小王公司”
                m = re.search(
                    r"(?:删除|移除)?\s*(?:客户|购买单位|单位)\s*(?:叫|是|名称是|名为)?\s*[:：]?\s*([^\s，,。]{2,60}?)"
                    r"(?=(?:联系人|电话|手机|手机号|联系电话|联系号码|地址|住址)|\s*$)",
                    order_text,
                )
                if m:
                    target_name = (m.group(1) or "").strip()

            deleted_count = 0
            if target_id:
                try:
                    tid = int(target_id)
                    deleted_count = query_service.delete(PurchaseUnit, id=tid)
                except RECOVERABLE_ERRORS:
                    deleted_count = 0
            elif target_name:
                deleted_count = query_service.delete(PurchaseUnit, unit_name=target_name)
                if deleted_count == 0 and target_name:
                    try:
                        from app.infrastructure.lookups.purchase_unit_resolver import (
                            resolve_purchase_unit,
                        )

                        resolved = resolve_purchase_unit(target_name)
                        if (
                            resolved
                            and getattr(resolved, "unit_name", None)
                            and resolved.unit_name != target_name
                        ):
                            deleted_count = query_service.delete(
                                PurchaseUnit, unit_name=resolved.unit_name
                            )
                    except RECOVERABLE_ERRORS as e:
                        logger.warning("解析购买单位失败: %s", e)

            return _j(
                {
                    "success": True,
                    "message": "删除成功" if deleted_count > 0 else "删除成功（未找到匹配记录）",
                    "deleted_count": deleted_count,
                },
                200,
            )
        # 聊天创建购买单位兜底：
        # 当用户表达“添加客户/购买单位 + 名称/联系人/电话/地址”时，直接写入 purchase_units。
        # 这与前端 pro-feature-widget 里 POST /api/purchase_units 的字段对齐。
        should_create_purchase_unit = (
            str(effective_action)
            in {"add", "create", "添加", "新增", "添加客户", "添加购买单位", "create_purchase_unit"}
            or has_add_verb
        )

        # 补充客户信息处理（他/她/它的 联系人/电话/地址）
        should_supplement = str(effective_action) in {"supplement", "补充"} or params.get(
            "field_name"
        )

        if should_supplement:
            from app.db.models import PurchaseUnit
            from app.db.session import get_db
            from app.services import get_task_context_service
            from app.services.unified_query_service import query_service

            ctx = get_task_context_service()
            user_id = params.get("user_id") or _hdr("X-User-ID", "default")

            last_customer = ctx.get_last_customer(user_id)
            field_name = params.get("field_name", "")
            field_value = params.get("field_value", "")

            if not field_name and order_text:
                m = re.search(
                    r"(?:联系人|联系电话|电话|手机|地址)\s*(?:是|：|:)?\s*(.{1,30})", order_text
                )
                if m:
                    field_name = "contact_person"
                    field_value = m.group(1).strip()

            if not field_value and order_text:
                if field_name == "contact_person":
                    m = re.search(
                        r"(?:联系人|联系人是)\s*(?:是|：|:)?\s*([^\s，,。]{1,20})", order_text
                    )
                    if m:
                        field_value = m.group(1).strip()
                elif field_name in ("contact_phone", "contact_address"):
                    m = re.search(
                        r"(?:电话|手机|地址)\s*(?:是|：|:)?\s*([^\s，,。]{1,50})", order_text
                    )
                    if m:
                        field_value = m.group(1).strip()

            if not last_customer and not field_value:
                return _j(
                    {
                        "success": False,
                        "message": "请先告诉我要补充哪个客户的联系人信息，例如：添加客户七彩乐园",
                    },
                    400,
                )

            target_name = last_customer.get("customer_name") if last_customer else None
            if not target_name:
                m = re.search(
                    r"(?:客户|购买单位|单位)\s*(?:是|叫|名称是|名为)?\s*[:：]?\s*([^\s，,。]{2,30})",
                    order_text,
                )
                if m:
                    target_name = (m.group(1) or "").strip()

            if not target_name:
                return _j({"success": False, "message": "请告诉我要补充哪个客户的联系人信息"}, 400)

            field_map = {
                "contact_person": "联系人",
                "contact_phone": "联系电话",
                "contact_address": "地址",
            }
            field_label = field_map.get(field_name, field_name)

            from app.services.unified_query_service import query_service

            customer = query_service.get_first(PurchaseUnit, unit_name=target_name)
            if not customer:
                return _j({"success": False, "message": f"未找到客户：{target_name}"}, 404)

            if field_name == "contact_person":
                customer.contact_person = field_value
            elif field_name == "contact_phone":
                customer.contact_phone = field_value
            elif field_name == "contact_address":
                customer.address = field_value

            with get_db() as db:
                db.commit()

            return _j(
                {
                    "success": True,
                    "message": f"已为 {target_name} 补充 {field_label}：{field_value}",
                    "data": {
                        "id": customer.id,
                        "customer_name": customer.unit_name,
                        "contact_person": customer.contact_person,
                        "contact_phone": customer.contact_phone,
                        "contact_address": customer.address,
                    },
                },
                200,
            )
        if should_create_purchase_unit:
            import re

            from app.application import get_customer_app_service
            from app.db.session import get_db

            unit_name = (
                params.get("unit_name") or params.get("name") or params.get("customer_name") or ""
            ).strip()
            contact_person = (params.get("contact_person") or "").strip()
            contact_phone = (params.get("contact_phone") or "").strip()
            address = (params.get("address") or params.get("contact_address") or "").strip()

            # 兼容：有些模型/上游会把“购买单位 + 联系人”拼成一个字段，
            # 例如：unit_name = "七彩乐园联系人向总"。
            # 这里对 unit_name 做关键词前截断，避免把联系人尾部污染客户名。
            if unit_name:
                m_unit = re.match(
                    r"^(.+?)(?=(联系人|电话|手机|手机号|联系电话|联系号码|地址|住址|联系地址|$))",
                    unit_name,
                )
                if m_unit and (m_unit.group(1) or "").strip():
                    unit_name = m_unit.group(1).strip()

            # 从自然语言中尽量提取字段（例如：“添加一个客户叫七彩乐园，联系人是向总”）
            if not unit_name and order_text:
                m = re.search(
                    r"(?:客户|购买单位|单位)\s*(?:是|叫|名称是|名为)?\s*[:：]?\s*([^\s，,。]{2,30})",
                    order_text,
                )
                if m:
                    unit_name = (m.group(1) or "").strip()

            if not contact_person and order_text:
                m = re.search(r"(?:联系人|联系人是)\s*(?:是|：)?\s*([^\s，,。]{1,20})", order_text)
                if m:
                    contact_person = (m.group(1) or "").strip()

            if not contact_phone and order_text:
                m = re.search(
                    r"(?:电话|手机|手机号|联系电话|联系号码)\s*(?:是|：)?\s*(\d{5,20})", order_text
                )
                if m:
                    contact_phone = (m.group(1) or "").strip()

            if not address and order_text:
                m = re.search(r"(?:地址|住址|联系地址)\s*(?:是|：)?\s*([^，,。]{2,80})", order_text)
                if m:
                    address = (m.group(1) or "").strip()

            logger.info(
                "customers: create extracted unit_name=%s contact_person=%s contact_phone=%s address=%s",
                unit_name,
                contact_person,
                contact_phone,
                address,
            )

            if not unit_name:
                logger.warning("customers: create skipped due to missing unit_name")
                return _j({"success": False, "message": "缺少购买单位参数（unit_name/name）"}, 400)

            # 为了让聊天添加在界面上可见，同时保证发货单能解析：
            # - `customers` 表：系统唯一来源（发货单解析也只从 customers 解析）

            # 1) 写入 customers（用于前端显示 & 供发货单解析）
            customer_data = {
                "customer_name": unit_name,
                "contact_person": contact_person or None,
                "contact_phone": contact_phone or None,
                "contact_address": address or None,
            }
            customer_service = get_customer_app_service()
            customer_result = customer_service.create(customer_data)
            if customer_result.get("success"):
                logger.info("customers: customer created customer_name=%s", unit_name)

                from app.services import get_task_context_service

                ctx = get_task_context_service()
                user_id = _hdr("X-User-ID", "default")
                ctx.set_last_customer(
                    user_id,
                    {
                        "customer_name": unit_name,
                        "contact_person": contact_person,
                        "contact_phone": contact_phone,
                        "contact_address": address,
                    },
                )

                return _j(customer_result, 201)

            # 幂等：客户已存在也视为成功（避免前端把“已存在”当失败）
            msg = customer_result.get("message") or ""
            if "客户名称已存在" in msg:
                from app.services.unified_query_service import find_purchase_unit

                exists = find_purchase_unit(unit_name=unit_name)
                customer_id = exists["id"] if exists else None
                return _j(
                    {
                        "success": True,
                        "message": "已存在",
                        "data": {
                            "id": customer_id,
                            "customer_name": unit_name,
                            "contact_person": (exists.get("contact_person") if exists else None),
                            "contact_phone": (exists.get("contact_phone") if exists else None),
                            "contact_address": (exists.get("address") if exists else None),
                        },
                    },
                    201,
                )
            return _j(customer_result, 400)

        return _j({"success": True, "message": "客户管理"})

    return NOT_HANDLED
