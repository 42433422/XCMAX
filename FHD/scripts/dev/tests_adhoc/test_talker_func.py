# -*- coding: utf-8 -*-
import sys
import os

sys.path.insert(0, r"E:\FHD\XCAGI")
from app.db.models import WechatContact
from app.db.session import get_db
from app.services.wechat_contact_service import get_wechat_contact_service
from app.utils.path_utils import get_resource_path

msg_db = os.path.join(get_resource_path("wechat-decrypt"), "decrypted", "message", "message_0.db")
print(f"DB exists: {os.path.exists(msg_db)}")

wechat_id = "wxid_tfxzqdqt87oa22"
print(f"Searching for: {wechat_id}")

with get_db() as db:
    contact = (
        db.query(WechatContact)
        .filter(WechatContact.wechat_id == wechat_id, WechatContact.is_active == 1)
        .first()
    )
    if not contact:
        raise SystemExit(f"Contact not found: {wechat_id}")

    result = get_wechat_contact_service().refresh_messages(contact.id, limit=50)
    print(f"Refresh result: {result}")
