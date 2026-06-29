"""Employee and enterprise-customer IM helpers for ``ImApplicationService``."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select

from app.db.models.ai_employee import AiEmployeeProfile
from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.user import User
from app.utils.time import utc_now_naive

logger = logging.getLogger(__name__)

AI_EMPLOYEE_USERNAME_PREFIX = "ai-employee:"
AI_EMPLOYEE_ROLE = "ai_employee"


class ImEmployeeMixin:
    def enterprise_cs_user_id(self) -> int | None:
        cs = self._ensure_enterprise_dedicated_cs_user()
        return int(cs.id) if cs is not None else None

    def ensure_employee_user(
        self,
        employee_id: str,
        *,
        mod_id: str = "",
        display_name: str = "",
        avatar_url: str = "",
        owner_user_id: int = 0,
    ) -> int:
        """Create or refresh the virtual IM user for an AI employee."""
        eid = str(employee_id or "").strip()
        if not eid:
            raise ValueError("employee_id 必填")
        username = f"{AI_EMPLOYEE_USERNAME_PREFIX}{eid}"
        row = (
            self._db.execute(select(User).where(User.username == username).limit(1))
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
        """Return the per-employee owner user id, or 0 when not configured."""
        eid = str(employee_id or "").strip()
        if not eid:
            return 0
        row = self._db.execute(
            select(AiEmployeeProfile.owner_user_id)
            .where(AiEmployeeProfile.employee_id == eid)
            .limit(1)
        ).first()
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
        """Return direct IM summaries keyed by employee id."""
        boss_uid_int = int(boss_uid or 0)
        if boss_uid_int <= 0:
            return {}
        eid_to_meta: dict[str, dict[str, Any]] = {}
        for emp in employees:
            eid = str(emp.get("id") or "").strip()
            if eid:
                eid_to_meta[eid] = {
                    "mod_id": str(emp.get("mod_id") or emp.get("market_pkg_id") or "").strip(),
                    "display_name": str(
                        emp.get("name") or emp.get("label") or emp.get("title") or eid
                    ).strip(),
                    "avatar_url": str(
                        emp.get("avatar_url") or emp.get("market_avatar") or ""
                    ).strip(),
                }
        if not eid_to_meta:
            return {}
        profiles = (
            self._db.execute(
                select(AiEmployeeProfile).where(
                    AiEmployeeProfile.employee_id.in_(list(eid_to_meta.keys()))
                )
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
                except Exception:  # noqa: BLE001 - best-effort enrichment for employee list rows
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
                # 注意：移动端 WorkflowEmployeeInfo.im_last_message_at 是非空 String，
                # 返回 null 会让 Gson 把 null 灌进非空字段、构造时 NPE 崩溃。统一用 ""。
                "im_last_message_at": (
                    conv.last_message_at.isoformat() if conv.last_message_at else ""
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
                            "im_last_message_at": "",
                            "im_unread_count": 0,
                        }
                except Exception:  # noqa: BLE001 - summary must tolerate one employee bootstrap failure
                    logger.debug("get_or_create_direct failed for employee %s", eid, exc_info=True)
        return out

    def set_employee_owner(self, employee_id: str, owner_user_id: int) -> bool:
        """Set the per-employee owner user id."""
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
            self._db.execute(select(User.id).where(User.id == owner_uid).limit(1)).scalars().first()
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
        """Send one IM message from an AI employee to the boss user."""
        text = (body or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        boss_uid_int = int(boss_uid)
        if boss_uid_int <= 0:
            raise ValueError("boss_user_id 非法")
        boss_exists = (
            self._db.execute(select(User).where(User.id == boss_uid_int).limit(1)).scalars().first()
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
        """List enterprise-customer conversations visible to the operator CS inbox."""
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
        """Read an enterprise-customer conversation as the dedicated CS user."""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            return []
        messages = self.list_messages(conversation_id, cs_id, limit=100)
        # 运营者读取即视为已读:推进共享客服用户 cs_id 的已读游标,清掉收件箱未读红点。
        # 客服未读按虚拟客服用户 cs_id 计(list_cs_inbox 的 _count_unread(conv, cs_id)),
        # 标准 im_mark_read 标的是运营者自己的 uid、标不到这里,故必须在读取时显式标 cs_id。
        try:
            last_id = int(messages[-1].get("id") or 0) if messages else 0
            if last_id > 0:
                self.mark_read(conversation_id, int(cs_id), last_id)
        except Exception:  # noqa: BLE001 - 标已读失败不应影响读消息本身
            logger.debug("cs_inbox_messages mark_read skipped", exc_info=True)
        return messages

    def cs_reply(self, conversation_id: int, body: str) -> dict[str, Any]:
        """Reply as the dedicated enterprise CS user."""
        cs_id = self.enterprise_cs_user_id()
        if cs_id is None:
            raise ValueError("客服通道不可用")
        return self.send_message(conversation_id, cs_id, body)
