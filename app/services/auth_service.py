from datetime import datetime
from typing import Any, Dict, Optional

from app.utils.password_hash import check_password_hash, generate_password_hash

from app.db.models import Permission, Role, User
from app.db.session import get_db
from app.services.session_service import get_session_service
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import NeuroEvent, EventPriority



class AuthService:
    def __init__(self):
        self.session_service = get_session_service()


    def _publish_event(self, event_type: str, payload: dict, priority: 'EventPriority' = None) -> str:
        """发布领域事件"""
        if priority is None:
            priority = EventPriority.NORMAL
        try:
            bus = get_neuro_bus()
            event = NeuroEvent(
                event_type=event_type,
                payload=payload,
                source=self.__class__.__name__,
                priority=priority
            )
            bus.publish(event)
            return event.metadata.event_id
        except Exception as e:
            logger.warning(f"发布事件失败 {event_type}: {e}")
            return ""

    def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        with get_db() as db:
            try:
                user = db.query(User).filter(User.username == username).first()

                if not user:
                    return {"success": False, "message": "用户名或密码错误"}

                if not user.is_active:
                    return {"success": False, "message": "账户已被禁用"}

                if not check_password_hash(user.password, password):
                    return {"success": False, "message": "用户名或密码错误"}

                user.last_login = datetime.utcnow()
                db.commit()

                session_result = self.session_service.create_session(user.id)
                if not session_result["success"]:
                    return {"success": False, "message": "会话创建失败"}

                return {
                    "success": True,
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                        "email": user.email,
                        "role": user.role
                    },
                    "session_id": session_result["session_id"],
                    "expires_at": session_result["expires_at"]
                }
            except Exception as e:
                return {"success": False, "message": str(e)}

    def logout(self, session_id: str) -> bool:
        return self.session_service.delete_session(session_id)

    def get_current_user(self, session_id: str) -> Optional[User]:
        return self.session_service.validate_session(session_id)

    def get_user_permissions(self, user: User) -> list:
        with get_db() as db:
            if user.role == "admin":
                perms = db.query(Permission).all()
                return [p.code for p in perms]

            role = db.query(Role).filter(Role.name == user.role).first()
            if not role:
                return []
            return [p.code for p in role.permissions]

    def has_permission(self, user: User, permission_code: str) -> bool:
        if user.role == "admin":
            return True

        perms = self.get_user_permissions(user)
        return permission_code in perms

    def change_password(self, user_id: int, old_password: str, new_password: str) -> Dict[str, Any]:
        with get_db() as db:
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "message": "用户不存在"}

                if not check_password_hash(user.password, old_password):
                    return {"success": False, "message": "原密码错误"}

                user.password = generate_password_hash(new_password)
                db.commit()
                return {"success": True, "message": "密码修改成功"}
            except Exception as e:
                db.rollback()
                return {"success": False, "message": str(e)}

    def reset_password(self, user_id: int, new_password: str) -> Dict[str, Any]:
        with get_db() as db:
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return {"success": False, "message": "用户不存在"}

                user.password = generate_password_hash(new_password)
                db.commit()
                self.session_service.delete_user_sessions(user_id)
                return {"success": True, "message": "密码已重置，请使用新密码登录"}
            except Exception as e:
                db.rollback()
                return {"success": False, "message": str(e)}


_auth_service = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(AuthService, "app.services.auth_service")

