"""微信解密缓存 sqlite 读取（从 compat 路由迁出）。"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing

logger = logging.getLogger(__name__)


def load_contact_display_names(contact_db_path: str) -> dict[str, str]:
    """username -> 显示名（remark > nick > username）。"""
    names: dict[str, str] = {}
    if not contact_db_path:
        return names
    try:
        with closing(sqlite3.connect(contact_db_path)) as conn:
            for uname, nick, remark in conn.execute(
                "SELECT username, nick_name, remark FROM contact"
            ).fetchall():
                names[uname] = remark or nick or uname
    except Exception:
        logger.debug("load_contact_display_names failed", exc_info=True)
    return names


def query_session_feed(session_db_path: str, *, limit: int) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(session_db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT username, unread_count, summary, last_timestamp,
                   last_msg_type, last_msg_sender, last_sender_display_name
            FROM SessionTable
            WHERE last_timestamp > 0
            ORDER BY last_timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
