"""IM V0 应用服务。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models.ai_employee import AiEmployeeProfile
from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.user import User
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

ENTERPRISE_DEDICATED_CS_USERNAME = "enterprise-cs"
ENTERPRISE_DEDICATED_CS_DISPLAY_NAME = "企业专属客服"

AI_EMPLOYEE_USERNAME_PREFIX = "ai-employee:"
AI_EMPLOYEE_ROLE = "ai_employee"


def ensure_im_tables(engine) -> None:
    from app.db.init_db import init_im_tables

    init_im_tables(engine)


class ImApplicationService:
    def __init__(self, db: Session):
        self._db = db

    def _display_name(self, user_id: int) -> str:
        user = self._db.get(User, int(user_id))
        if not user:
            return f"用户{user_id}"
        name = str(user.display_name or "").strip() or str(user.username or "").strip()
        return name or f"用户{user_id}"

    def _display_name_map(self, user_ids: list[int]) -> dict[int, str]:
        ids = [int(u) for u in set(user_ids)]
        if not ids:
            return {}
        rows = self._db.execute(select(User).where(User.id.in_(ids))).scalars().all()
        out: dict[int, str] = {}
        for u in rows:
            name = str(u.display_name or "").strip() or str(u.username or "").strip()
            out[int(u.id)] = name or f"用户{u.id}"
        return out

    @staticmethod
    def _is_enterprise_dedicated_cs_user(user: User | None) -> bool:
        return (
            user is not None
            and str(getattr(user, "username", "") or "").strip().lower()
            == ENTERPRISE_DEDICATED_CS_USERNAME
        )

    def _ensure_enterprise_dedicated_cs_user(self) -> User | None:
        row = (
            self._db.execute(
                select(User).where(User.username == ENTERPRISE_DEDICATED_CS_USERNAME).limit(1)
            )
            .scalars()
            .first()
        )
        if row is None:
            row = User(
                username=ENTERPRISE_DEDICATED_CS_USERNAME,
                password="!",
                display_name=ENTERPRISE_DEDICATED_CS_DISPLAY_NAME,
                email="",
                role="support",
                is_active=True,
                created_at=utc_now_naive(),
            )
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
            return row

        changed = False
        if str(row.display_name or "").strip() != ENTERPRISE_DEDICATED_CS_DISPLAY_NAME:
            row.display_name = ENTERPRISE_DEDICATED_CS_DISPLAY_NAME
            changed = True
        if not bool(row.is_active):
            row.is_active = True
            changed = True
        if changed:
            self._db.commit()
            self._db.refresh(row)
        return row

    @staticmethod
    def _contact_dict(user: User, *, dedicated_cs: bool = False) -> dict[str, Any]:
        name = str(user.display_name or "").strip() or str(user.username or "").strip()
        out: dict[str, Any] = {
            "id": int(user.id),
            "display_name": name or f"用户{user.id}",
            "username": str(user.username or "").strip(),
        }
        if dedicated_cs:
            out["is_enterprise_dedicated_cs"] = True
        return out

    def _direct_peer_id(self, conversation_id: int, user_id: int) -> int | None:
        row = self._db.execute(
            select(ImConversationMember.user_id).where(
                ImConversationMember.conversation_id == conversation_id,
                ImConversationMember.user_id != user_id,
            )
        ).first()
        return int(row[0]) if row else None

    def list_conversations(
        self, user_id: int, *, include_enterprise_dedicated_cs: bool = True
    ) -> list[dict[str, Any]]:
        rows = (
            self._db.execute(
                select(ImConversation)
                .join(
                    ImConversationMember,
                    ImConversationMember.conversation_id == ImConversation.id,
                )
                .where(ImConversationMember.user_id == user_id)
                .order_by(desc(ImConversation.last_message_at), desc(ImConversation.id))
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for conv in rows:
            last_msg = (
                self._db.execute(
                    select(ImMessage)
                    .where(ImMessage.conversation_id == conv.id)
                    .order_by(desc(ImMessage.id))
                    .limit(1)
                )
                .scalars()
                .first()
            )
            unread = self._count_unread(conv.id, user_id)
            if conv.is_direct:
                peer_id = self._direct_peer_id(conv.id, user_id)
                peer = self._db.get(User, int(peer_id)) if peer_id else None
                title = (
                    self._display_name(peer_id) if peer_id else (conv.title or f"会话 #{conv.id}")
                )
            else:
                peer = None
                title = conv.title or f"会话 #{conv.id}"
            item: dict[str, Any] = {
                "id": conv.id,
                "title": title,
                "is_direct": conv.is_direct,
                "last_message_at": (
                    conv.last_message_at.isoformat() if conv.last_message_at else None
                ),
                "last_message_preview": (last_msg.body[:120] if last_msg else ""),
                "unread_count": unread,
            }
            is_enterprise_dedicated_cs = conv.is_direct and self._is_enterprise_dedicated_cs_user(
                peer
            )
            if is_enterprise_dedicated_cs and not include_enterprise_dedicated_cs:
                continue
            if is_enterprise_dedicated_cs:
                item["is_enterprise_dedicated_cs"] = True
            out.append(item)
        return out

    def list_contacts(
        self, user_id: int, *, include_enterprise_dedicated_cs: bool = True
    ) -> list[dict[str, Any]]:
        me = self._db.get(User, int(user_id))
        my_tenant = getattr(me, "tenant_id", None) if me else None
        dedicated_cs = (
            self._ensure_enterprise_dedicated_cs_user() if include_enterprise_dedicated_cs else None
        )
        dedicated_cs_id = (
            int(dedicated_cs.id) if dedicated_cs is not None and dedicated_cs.id else None
        )
        q = select(User).where(User.id != int(user_id), User.is_active.is_(True))
        if dedicated_cs_id is not None:
            q = q.where(User.id != dedicated_cs_id)
        elif not include_enterprise_dedicated_cs:
            q = q.where(User.username != ENTERPRISE_DEDICATED_CS_USERNAME)
        if my_tenant is not None:
            q = q.where(User.tenant_id == my_tenant)
        rows = self._db.execute(q.order_by(User.display_name, User.username)).scalars().all()
        out: list[dict[str, Any]] = []
        if dedicated_cs is not None and dedicated_cs_id != int(user_id):
            out.append(self._contact_dict(dedicated_cs, dedicated_cs=True))
        for u in rows:
            out.append(self._contact_dict(u))
        return out

    def _count_unread(self, conversation_id: int, user_id: int) -> int:
        member = self._get_member(conversation_id, user_id)
        last_read = int(member.last_read_message_id or 0) if member else 0
        return int(
            self._db.execute(
                select(func.count())
                .select_from(ImMessage)
                .where(
                    ImMessage.conversation_id == conversation_id,
                    ImMessage.id > last_read,
                    ImMessage.sender_user_id != user_id,
                )
            ).scalar()
            or 0
        )

    def _get_member(self, conversation_id: int, user_id: int) -> ImConversationMember | None:
        return self._db.execute(
            select(ImConversationMember).where(
                ImConversationMember.conversation_id == conversation_id,
                ImConversationMember.user_id == user_id,
            )
        ).scalar_one_or_none()

    def get_or_create_direct(self, user_id: int, peer_user_id: int) -> dict[str, Any]:
        if user_id == peer_user_id:
            raise ValueError("不能与自己创建会话")
        conv_id = self._find_direct_conversation(user_id, peer_user_id)
        if conv_id:
            conv = self._db.get(ImConversation, conv_id)
            return {"id": conv.id, "title": conv.title, "created": False}
        conv = ImConversation(
            title=f"用户{user_id} ↔ 用户{peer_user_id}",
            is_direct=True,
        )
        self._db.add(conv)
        self._db.flush()
        for uid in (user_id, peer_user_id):
            self._db.add(ImConversationMember(conversation_id=conv.id, user_id=uid))
        self._db.commit()
        self._db.refresh(conv)
        return {"id": conv.id, "title": conv.title, "created": True}

    def _find_direct_conversation(self, a: int, b: int) -> int | None:
        sub_a = select(ImConversationMember.conversation_id).where(
            ImConversationMember.user_id == a
        )
        sub_b = select(ImConversationMember.conversation_id).where(
            ImConversationMember.user_id == b
        )
        row = self._db.execute(
            select(ImConversation.id)
            .where(
                ImConversation.is_direct.is_(True),
                ImConversation.id.in_(sub_a),
                ImConversation.id.in_(sub_b),
            )
            .limit(1)
        ).first()
        return int(row[0]) if row else None

    def list_messages(
        self, conversation_id: int, user_id: int, *, limit: int = 50, before_id: int | None = None
    ) -> list[dict[str, Any]]:
        if not self._get_member(conversation_id, user_id):
            raise PermissionError("非会话成员")
        q = select(ImMessage).where(ImMessage.conversation_id == conversation_id)
        if before_id:
            q = q.where(ImMessage.id < before_id)
        rows = (
            self._db.execute(q.order_by(desc(ImMessage.id)).limit(min(limit, 100))).scalars().all()
        )
        rows = list(reversed(rows))
        names = self._display_name_map([m.sender_user_id for m in rows])
        return [self._message_dict(m, names.get(int(m.sender_user_id))) for m in rows]

    def send_message(self, conversation_id: int, sender_user_id: int, body: str) -> dict[str, Any]:
        if not self._get_member(conversation_id, sender_user_id):
            raise PermissionError("非会话成员")
        text = (body or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        msg = ImMessage(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            body=text[:4000],
        )
        self._db.add(msg)
        conv = self._db.get(ImConversation, conversation_id)
        if conv:
            conv.last_message_at = utc_now_naive()
        self._db.commit()
        self._db.refresh(msg)
        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_im_message_sent

            neuro_notify_im_message_sent(
                conversation_id=msg.conversation_id,
                sender_id=str(msg.sender_user_id),
                message_type="text",
            )
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_im_message_sent skipped", exc_info=True)
        member_ids = self._member_user_ids(conversation_id)
        message = self._message_dict(msg, self._display_name(sender_user_id))
        updated_at_ms = self._record_im_message_change(message, actor=str(sender_user_id))
        try:
            self._maybe_push_cs_message(conversation_id, sender_user_id, text, member_ids)
        except RECOVERABLE_ERRORS:
            logger.debug("cs push skipped", exc_info=True)
        return {
            "message": message,
            "member_user_ids": member_ids,
            "updated_at_ms": updated_at_ms,
        }

    def _query_admin_user_ids(self) -> list[int]:
        rows = self._db.execute(
            select(User.id).where(
                User.is_active.is_(True),
                User.role.in_(["admin", "super_admin", "owner"]),
            )
        ).all()
        return [int(r[0]) for r in rows]

    def _maybe_push_cs_message(
        self, conversation_id: int, sender_user_id: int, text: str, member_ids: list[int]
    ) -> None:
        """专属客服会话消息推送:客户发→推所有运营者(admin);客服回→推客户。

        CS 端点直接调 send_message(绕过会做推送的 im_send_message 路由),故在此统一补推。
        非客服会话(enterprise-cs 不在会话成员里)直接跳过,不影响普通 IM。
        """
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None or int(cs_id) not in [int(m) for m in member_ids]:
            return
        try:
            from app.services.mobile_push import notify_user
        except ImportError:
            return
        preview = (text or "").strip()[:120]
        if int(sender_user_id) == int(cs_id):
            # 运营者以企业专属客服身份回复 → 推给客户
            customer_id = self._direct_peer_id(conversation_id, int(cs_id))
            if customer_id:
                try:
                    notify_user(
                        int(customer_id),
                        "专属客服回复",
                        preview,
                        {
                            "type": "cs_reply",
                            "conversation_id": str(conversation_id),
                            "route": "cs_chat",
                        },
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("cs reply push failed", exc_info=True)
        else:
            # 客户发消息 → 推给所有运营者(admin),进管理端「客户客服」收件箱
            sender_name = self._display_name(sender_user_id)
            for admin_id in self._query_admin_user_ids():
                if int(admin_id) == int(sender_user_id):
                    continue
                try:
                    notify_user(
                        int(admin_id),
                        f"客户咨询 · {sender_name}",
                        preview,
                        {
                            "type": "cs_inbox",
                            "conversation_id": str(conversation_id),
                            "route": "admin_cs_console",
                        },
                    )
                except RECOVERABLE_ERRORS:
                    logger.debug("cs inbox push failed", exc_info=True)

    def mark_read(self, conversation_id: int, user_id: int, last_message_id: int) -> dict[str, Any]:
        member = self._get_member(conversation_id, user_id)
        if not member:
            raise PermissionError("非会话成员")
        applied_read = max(int(member.last_read_message_id or 0), last_message_id)
        member.last_read_message_id = applied_read
        self._db.commit()
        updated_at_ms = self._record_im_read_change(
            conversation_id,
            user_id,
            applied_read,
            actor=str(user_id),
        )
        return {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "last_read_message_id": applied_read,
            "member_user_ids": self._member_user_ids(conversation_id),
            "updated_at_ms": updated_at_ms,
        }

    @staticmethod
    def _record_im_message_change(message: dict[str, Any], *, actor: str) -> int:
        from app.services.xcmax_sync_service import record_change, utc_now_ms

        updated_at_ms = utc_now_ms()
        record_change(
            "im_message",
            str(message["id"]),
            "insert",
            {**message, "meta": {"updated_at_ms": updated_at_ms}},
            actor=actor,
        )
        return updated_at_ms

    @staticmethod
    def _record_im_read_change(
        conversation_id: int,
        user_id: int,
        last_read_message_id: int,
        *,
        actor: str,
    ) -> int:
        from app.services.xcmax_sync_service import record_change, utc_now_ms

        updated_at_ms = utc_now_ms()
        record_change(
            "im_read_state",
            f"{conversation_id}:{user_id}",
            "update",
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "last_read_message_id": last_read_message_id,
                "meta": {"updated_at_ms": updated_at_ms},
            },
            actor=actor,
        )
        return updated_at_ms

    def _member_user_ids(self, conversation_id: int) -> list[int]:
        rows = self._db.execute(
            select(ImConversationMember.user_id).where(
                ImConversationMember.conversation_id == conversation_id
            )
        ).all()
        return [int(r[0]) for r in rows]

    # ── 运营者(管理端)客服收件箱:企业客户↔企业专属客服 ──

    def enterprise_cs_user_id(self) -> int | None:
        cs = self._ensure_enterprise_dedicated_cs_user()
        return int(cs.id) if cs is not None else None

    # ── AI 员工 IM 身份：让员工像真人一样出现在 IM 会话里 ──

    def ensure_employee_user(
        self,
        employee_id: str,
        *,
        mod_id: str = "",
        display_name: str = "",
        avatar_url: str = "",
        owner_user_id: int = 0,
    ) -> int:
        """为员工建虚拟 User 行（幂等），返回 user_id。

        仿 `_ensure_enterprise_dedicated_cs_user` 范式：
        - username 固定为 `ai-employee:{employee_id}`，便于按 username 查重
        - role=`ai_employee`，区别于真人/客服
        - 同时写 `AiEmployeeProfile` 缓存 mod_id/display_name/avatar_url/owner_user_id
        """
        eid = str(employee_id or "").strip()
        if not eid:
            raise ValueError("employee_id 必填")
        username = f"{AI_EMPLOYEE_USERNAME_PREFIX}{eid}"
        row = (
            self._db.execute(
                select(User).where(User.username == username).limit(1)
            )
            .scalars()
            .first()
        )
        name = display_name.strip() or eid
        avatar = (avatar_url or "").strip()
        if row is None:
            row = User(
                username=username,
                password="!",
                display_name=name,
                email="",
                role=AI_EMPLOYEE_ROLE,
                is_active=True,
                created_at=utc_now_naive(),
            )
            self._db.add(row)
            self._db.flush()
        else:
            changed = False
            if str(row.display_name or "").strip() != name:
                row.display_name = name
                changed = True
            if not bool(row.is_active):
                row.is_active = True
                changed = True
            if changed:
                self._db.flush()

        profile = (
            self._db.execute(
                select(AiEmployeeProfile).where(AiEmployeeProfile.employee_id == eid).limit(1)
            )
            .scalars()
            .first()
        )
        if profile is None:
            profile = AiEmployeeProfile(
                employee_id=eid,
                user_id=int(row.id),
                mod_id=mod_id or "",
                display_name=name,
                avatar_url=avatar,
                owner_user_id=int(owner_user_id or 0),
            )
            self._db.add(profile)
        else:
            profile.user_id = int(row.id)
            profile.mod_id = mod_id or profile.mod_id
            profile.display_name = name
            profile.avatar_url = avatar or profile.avatar_url
            if int(owner_user_id or 0) > 0:
                profile.owner_user_id = int(owner_user_id)
        self._db.commit()
        self._db.refresh(row)
        return int(row.id)

    def get_employee_owner(self, employee_id: str) -> int:
        """查员工的专属老板 user_id（per-employee owner），未配返回 0。

        MODstore 调用方优先用员工自己的 owner，未配再回退 env `FHD_BOSS_USER_ID`。
        """
        eid = str(employee_id or "").strip()
        if not eid:
            return 0
        row = (
            self._db.execute(
                select(AiEmployeeProfile.owner_user_id)
                .where(AiEmployeeProfile.employee_id == eid)
                .limit(1)
            )
            .first()
        )
        if row is None:
            return 0
        try:
            oid = int(row[0] or 0)
            return oid if oid > 0 else 0
        except (TypeError, ValueError):
            return 0

    def employee_im_summary(
        self, boss_uid: int, employees: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """批量查员工与老板的 direct IM 会话摘要，返回 {employee_id: {im_conv_id, im_last_message, im_last_message_at, im_unread_count}}。

        供 admin_home 把员工列表项与 IM 会话打通，让 App 在现有员工列表里直接看到/点进 IM 会话。
        对于尚无 IM 虚拟用户或 direct 会话的员工，自动 ensure 虚拟用户 + 创建空 direct 会话，
        确保老板首次点击员工聊天页时 im_conv_id > 0，能正常走 IM 消息通道。
        """
        boss_uid_int = int(boss_uid or 0)
        if boss_uid_int <= 0:
            return {}
        eid_to_meta: dict[str, dict[str, Any]] = {}
        for emp in employees:
            eid = str(emp.get("id") or "").strip()
            if eid:
                eid_to_meta[eid] = {
                    "mod_id": str(emp.get("mod_id") or emp.get("market_pkg_id") or "").strip(),
                    "display_name": str(emp.get("name") or emp.get("label") or emp.get("title") or eid).strip(),
                    "avatar_url": str(emp.get("avatar_url") or emp.get("market_avatar") or "").strip(),
                }
        if not eid_to_meta:
            return {}
        profiles = (
            self._db.execute(
                select(AiEmployeeProfile).where(AiEmployeeProfile.employee_id.in_(list(eid_to_meta.keys())))
            )
            .scalars()
            .all()
        )
        eid_to_uid: dict[str, int] = {}
        for p in profiles:
            if p.user_id:
                eid_to_uid[str(p.employee_id)] = int(p.user_id)
        for eid, meta in eid_to_meta.items():
            if eid not in eid_to_uid:
                try:
                    uid = self.ensure_employee_user(
                        eid,
                        mod_id=meta["mod_id"],
                        display_name=meta["display_name"],
                        avatar_url=meta["avatar_url"],
                    )
                    eid_to_uid[eid] = uid
                except Exception:
                    logger.debug("ensure_employee_user failed for %s", eid, exc_info=True)
        if not eid_to_uid:
            return {}
        uid_to_eid = {int(v): k for k, v in eid_to_uid.items()}
        convs = (
            self._db.execute(
                select(ImConversation)
                .join(
                    ImConversationMember,
                    ImConversationMember.conversation_id == ImConversation.id,
                )
                .where(
                    ImConversationMember.user_id == boss_uid_int,
                    ImConversation.is_direct.is_(True),
                )
            )
            .scalars()
            .all()
        )
        out: dict[str, dict[str, Any]] = {}
        for conv in convs:
            peer_id = self._direct_peer_id(conv.id, boss_uid_int)
            if not peer_id or peer_id not in uid_to_eid:
                continue
            eid = uid_to_eid[peer_id]
            last_msg = (
                self._db.execute(
                    select(ImMessage)
                    .where(ImMessage.conversation_id == conv.id)
                    .order_by(desc(ImMessage.id))
                    .limit(1)
                )
                .scalars()
                .first()
            )
            out[eid] = {
                "im_conv_id": conv.id,
                "im_last_message": (last_msg.body[:120] if last_msg else ""),
                "im_last_message_at": (
                    conv.last_message_at.isoformat() if conv.last_message_at else None
                ),
                "im_unread_count": self._count_unread(conv.id, boss_uid_int),
            }
        for eid, emp_uid in eid_to_uid.items():
            if eid not in out:
                try:
                    conv = self.get_or_create_direct(boss_uid_int, emp_uid)
                    conv_id = int(conv.get("id") or 0)
                    if conv_id > 0:
                        out[eid] = {
                            "im_conv_id": conv_id,
                            "im_last_message": "",
                            "im_last_message_at": None,
                            "im_unread_count": 0,
                        }
                except Exception:
                    logger.debug("get_or_create_direct failed for employee %s", eid, exc_info=True)
        return out

    def set_employee_owner(self, employee_id: str, owner_user_id: int) -> bool:
        """设置员工的专属老板 user_id（per-employee owner）。

        校验：员工档案必须已存在；owner_user_id 必须是真实存在的用户。
        返回 False 表示档案不存在或 owner 无效/不存在。
        """
        eid = str(employee_id or "").strip()
        if not eid or int(owner_user_id or 0) <= 0:
            return False
        profile = (
            self._db.execute(
                select(AiEmployeeProfile).where(AiEmployeeProfile.employee_id == eid).limit(1)
            )
            .scalars()
            .first()
        )
        if profile is None:
            return False
        owner_uid = int(owner_user_id)
        owner_exists = (
            self._db.execute(
                select(User.id).where(User.id == owner_uid).limit(1)
            )
            .scalars()
            .first()
        )
        if owner_exists is None:
            raise ValueError(f"owner_user_id={owner_uid} 不存在")
        profile.owner_user_id = owner_uid
        self._db.commit()
        return True

    def send_employee_message(
        self,
        boss_uid: int,
        employee_id: str,
        body: str,
        *,
        mod_id: str = "",
        display_name: str = "",
        avatar_url: str = "",
        owner_user_id: int = 0,
    ) -> dict[str, Any]:
        """员工 → 老板发一条 IM 消息（自动触发 WS+FCM+离线 outbox）。

        流程：ensure_employee_user → get_or_create_direct(boss, employee) → send_message。
        send_message 内部已写 im_messages + 调 record_change 触发 WS push + CS 推送兜底。
        若传 owner_user_id > 0，会同时更新员工的 per-employee owner 表。
        """
        text = (body or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        boss_uid_int = int(boss_uid)
        if boss_uid_int <= 0:
            raise ValueError("boss_user_id 非法")
        boss_exists = (
            self._db.execute(
                select(User).where(User.id == boss_uid_int).limit(1)
            )
            .scalars()
            .first()
        )
        if boss_exists is None:
            raise ValueError(f"boss_user_id={boss_uid_int} 不存在")
        emp_uid = self.ensure_employee_user(
            employee_id,
            mod_id=mod_id,
            display_name=display_name,
            avatar_url=avatar_url,
            owner_user_id=owner_user_id,
        )
        conv = self.get_or_create_direct(int(boss_uid), emp_uid)
        result = self.send_message(int(conv["id"]), emp_uid, text)
        return {
            "conversation_id": conv["id"],
            "employee_user_id": emp_uid,
            "message": result.get("message"),
            "member_user_ids": result.get("member_user_ids") or [],
            "created": conv.get("created", False),
        }

    def list_cs_inbox(self) -> list[dict[str, Any]]:
        """运营者客服收件箱:所有「企业客户↔企业专属客服」会话(含手机端/桌面端,同一张 IM 表)。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            return []
        conv_ids = [
            int(r[0])
            for r in self._db.execute(
                select(ImConversationMember.conversation_id).where(
                    ImConversationMember.user_id == cs_id
                )
            ).all()
        ]
        if not conv_ids:
            return []
        rows = (
            self._db.execute(
                select(ImConversation)
                .where(ImConversation.id.in_(conv_ids), ImConversation.is_direct.is_(True))
                .order_by(desc(ImConversation.last_message_at))
            )
            .scalars()
            .all()
        )
        out: list[dict[str, Any]] = []
        for conv in rows:
            customer_id = self._direct_peer_id(int(conv.id), cs_id)
            if not customer_id:
                continue
            out.append(
                {
                    "id": int(conv.id),
                    "customer_user_id": int(customer_id),
                    "customer_name": self._display_name(int(customer_id)),
                    "last_message_at": conv.last_message_at.isoformat()
                    if conv.last_message_at
                    else "",
                    "unread_count": self._count_unread(int(conv.id), cs_id),
                }
            )
        return out

    def cs_inbox_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        """运营者读某客服会话历史(以 enterprise-cs 成员身份)。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            return []
        return self.list_messages(conversation_id, cs_id, limit=100)

    def cs_reply(self, conversation_id: int, body: str) -> dict[str, Any]:
        """运营者以「企业专属客服」身份回复客户。"""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            raise ValueError("客服通道不可用")
        return self.send_message(conversation_id, cs_id, body)

    @staticmethod
    def _message_dict(m: ImMessage, sender_name: str | None = None) -> dict[str, Any]:
        return {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender_user_id": m.sender_user_id,
            "sender_display_name": sender_name or f"用户{m.sender_user_id}",
            "body": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
