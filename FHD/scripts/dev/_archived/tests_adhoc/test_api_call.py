# -*- coding: utf-8 -*-
import sys
import os

sys.path.insert(0, r"E:\FHD\XCAGI")

from app.db.session import get_db
from app.db.models import WechatContact
from app.utils.path_utils import get_resource_path
from app.services.wechat_contact_cache_import import ensure_decrypted_wechat_dbs
from app.services.wechat_contact_service import get_wechat_contact_service

with get_db() as db:
    contact = db.query(WechatContact).filter(WechatContact.id == 1).first()
    if contact:
        wechat_id = contact.wechat_id or ""
        print(f"Contact wechat_id: '{wechat_id}'")

        sync_result = ensure_decrypted_wechat_dbs()
        print(f"Sync result: {sync_result}")

        decrypted_msg_dir = os.path.join(
            get_resource_path("wechat-decrypt"), "decrypted", "message"
        )
        msg_db_path = os.path.join(decrypted_msg_dir, "message_0.db")
        print(f"msg_db_path: {msg_db_path}, exists: {os.path.exists(msg_db_path)}")

        refresh_result = get_wechat_contact_service().refresh_messages(contact.id, limit=50)
        print(f"Refresh result: {refresh_result}")
    else:
        print("Contact not found")
