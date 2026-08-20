"""ImApplicationService 的「员工作为 IM 对端」mixin。

从 im_app_service 拆出以控制单文件行数（arch-fitness giant-file 上限）。IM 通道是用户↔用户；
AI 员工以「合成 User」（username=``emp:<employee_id>``）形态成为 1:1 对端，复用 dedicated-cs 同款做法，
从而每个员工拥有自己的聊天页、消息走 im-sync 实时多端同步 + 推送。

本 mixin 依赖宿主类（ImApplicationService）提供：``_db`` / ``get_or_create_direct`` /
``send_message`` / ``_direct_peer_id``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from app.db.models.user import User
from app.utils.time import utc_now_naive


class EmployeePeerMixin:
    if TYPE_CHECKING:
        _db: Any
        _direct_peer_id: Any
        get_or_create_direct: Any
        send_message: Any

    @staticmethod
    def employee_im_username(employee_id: str) -> str:
        return f"emp:{str(employee_id or '').strip()[:120]}"

    def _ensure_employee_im_user(self, employee_id: str, display_name: str = "") -> User | None:
        eid = str(employee_id or "").strip()
        if not eid:
            return None
        uname = self.employee_im_username(eid)
        nice = str(display_name or "").strip() or eid
        row = (
            self._db.execute(select(User).where(User.username == uname).limit(1)).scalars().first()
        )
        if row is None:
            row = User(
                username=uname,
                password="!",  # 合成账号不可登录
                display_name=nice,
                email="",
                role="employee",
                is_active=True,
                created_at=utc_now_naive(),
            )
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
            return row
        if display_name and str(row.display_name or "").strip() != nice:
            row.display_name = nice
            self._db.commit()
            self._db.refresh(row)
        return cast("User | None", row)

    def post_employee_message(
        self,
        *,
        boss_user_id: int,
        employee_id: str,
        body: str,
        display_name: str = "",
    ) -> dict[str, Any] | None:
        """以某 AI 员工的身份，向老板的 1:1 IM 会话发一条消息。

        用于「员工主动提问/汇报」出现在该员工的聊天页（出站半边）。返回 conversation_id + message，
        发送自动经 send_message 走 im-sync 变更记录 + 推送。``boss_user_id`` 必须是真实人类用户。
        """
        if int(boss_user_id or 0) <= 0:
            return None
        emp_user = self._ensure_employee_im_user(employee_id, display_name)
        if emp_user is None or int(emp_user.id) == int(boss_user_id):
            return None
        conv = self.get_or_create_direct(int(boss_user_id), int(emp_user.id))
        conv_id = int(conv["id"])
        sent = self.send_message(conv_id, int(emp_user.id), body)
        return {
            "conversation_id": conv_id,
            "employee_user_id": int(emp_user.id),
            "employee_id": str(employee_id or "").strip(),
            **sent,
        }

    def employee_id_for_conversation(self, conversation_id: int, boss_user_id: int) -> str | None:
        """若该 1:1 会话的对端是某 AI 员工合成 User，返回其 employee_id；否则 None。

        入站回流用：老板在某会话回复后，据此判断是否是「回复某员工」，是则把回复回流为该员工的答案。

        员工合成 User 有两套并存的命名（历史原因）：
        - ``emp:<employee_id>``（本 mixin ``post_employee_message`` 路径）
        - ``ai-employee:<employee_id>``（``/api/internal/employee-im/send`` 生产桥接路径，
          带 ``AiEmployeeProfile`` 档案）
        两者都必须识别，否则生产桥建的会话里老板的回复会被静默丢掉（已读不回）。
        兜底再按 ``AiEmployeeProfile.user_id`` 反查一次，容忍历史改名。
        """
        peer_id = self._direct_peer_id(conversation_id, int(boss_user_id))
        if not peer_id:
            return None
        peer = self._db.get(User, int(peer_id))
        uname = str(getattr(peer, "username", "") or "")
        for prefix in ("emp:", "ai-employee:"):
            if uname.startswith(prefix):
                return uname[len(prefix) :].strip() or None
        from app.db.models.ai_employee import AiEmployeeProfile

        prof_eid = self._db.execute(
            select(AiEmployeeProfile.employee_id)
            .where(AiEmployeeProfile.user_id == int(peer_id))
            .limit(1)
        ).first()
        if prof_eid and str(prof_eid[0] or "").strip():
            return str(prof_eid[0]).strip()
        return None
