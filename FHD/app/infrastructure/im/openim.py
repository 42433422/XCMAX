"""OpenIM transport adapter; employee execution records remain in the host audit store."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from functools import lru_cache

import httpx

from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.process_lock import exclusive_file_lock


def enabled() -> bool:
    return os.getenv("XCAGI_AI_GROUP_TRANSPORT", "") == "openim"


class OpenIMError(RuntimeError):
    pass


class OpenIMClient:
    def __init__(self, api: str, secret: str):
        self.api, self.secret = api.rstrip("/"), secret
        self.token, self.expires = "", 0.0

    def call(self, path: str, body: dict, *, authenticated: bool = True) -> dict:
        if authenticated and time.monotonic() >= self.expires:
            auth = self.call(
                "/auth/get_admin_token",
                {
                    "secret": self.secret,
                    "userID": os.getenv("XCAGI_OPENIM_ADMIN_ID", "imAdmin"),
                },
                authenticated=False,
            )
            self.token = auth["token"]
            self.expires = time.monotonic() + max(0, auth["expireTimeSeconds"] - 60)
        try:
            with httpx.Client(timeout=20, trust_env=False) as client:
                response = client.post(
                    self.api + path,
                    json=body,
                    headers={
                        "operationID": uuid.uuid4().hex,
                        "token": self.token if authenticated else "",
                    },
                )
                response.raise_for_status()
                result = response.json()
            if result.get("errCode") != 0:
                raise OpenIMError(f"OpenIM {path}: {result.get('errCode')}")
            return result.get("data") or {}
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenIMError("消息服务暂时不可用，请重新连接核对消息") from exc


@lru_cache(maxsize=4)
def _client(api: str, secret: str) -> OpenIMClient:
    if not api or not secret:
        raise OpenIMError("消息服务尚未配置")
    return OpenIMClient(api, secret)


class OpenIMGroups:
    def __init__(self, repository):
        tenant = current_tenant_id()
        if tenant is None:
            raise OpenIMError("消息服务缺少租户身份")
        self.tenant, self.repository = int(tenant), repository
        self.client = _client(
            os.getenv("XCAGI_OPENIM_API", ""), os.getenv("XCAGI_OPENIM_SECRET", "")
        )

    def identity(self, user_id: int, kind: str, value: str = "") -> str:
        digest = hashlib.sha256(value.encode()).hexdigest()[:24]
        return f"xc_t{self.tenant}_u{int(user_id)}_{kind}_{digest}"

    def ensure_group(self, group: dict) -> str:
        uid = int(group["user_id"])
        gid = self.identity(uid, "g", str(group["id"]))
        owner = self.identity(uid, "u")
        people = [{"userID": owner, "nickname": "我", "faceURL": ""}]
        people.extend(
            {
                "userID": self.identity(uid, "e", m["employee_id"]),
                "nickname": m.get("name") or m["employee_id"],
                "faceURL": "",
            }
            for m in group.get("members", [])
        )
        known = self.client.call("/user/get_users_info", {"userIDs": [p["userID"] for p in people]})
        registered = {p["userID"] for p in known.get("usersInfo") or []}
        missing = [p for p in people if p["userID"] not in registered]
        if missing:
            self.client.call("/user/user_register", {"users": missing})
        found = self.client.call("/group/get_groups_info", {"groupIDs": [gid]}).get(
            "groupInfos", []
        )
        if not found:
            self.client.call(
                "/group/create_group",
                {
                    "ownerUserID": owner,
                    "memberUserIDs": [p["userID"] for p in people[1:]],
                    "groupInfo": {
                        "groupID": gid,
                        "groupName": group["name"],
                        "groupType": 2,
                        "needVerification": 0,
                        "ex": "xcagi-employee-group",
                    },
                },
            )
        else:
            current: set[str] = set()
            page = 1
            while True:
                rows = (
                    self.client.call(
                        "/group/get_group_member_list",
                        {
                            "groupID": gid,
                            "pagination": {"pageNumber": page, "showNumber": 100},
                        },
                    ).get("members")
                    or []
                )
                current.update(m["userID"] for m in rows)
                if len(rows) < 100:
                    break
                page += 1
            desired = {p["userID"] for p in people}
            for path, ids in (
                ("invite_user_to_group", desired - current),
                ("kick_group", current - desired),
            ):
                if ids:
                    self.client.call(
                        "/group/" + path,
                        {
                            "groupID": gid,
                            "invitedUserIDs": sorted(ids),
                            "kickedUserIDs": sorted(ids),
                            "reason": "同步管理端群成员",
                        },
                    )
        return gid

    def sync(self, user_id: int, group_id: str) -> str:
        # A failed/uncertain publish is reconciled against OpenIM before re-sending.
        with exclusive_file_lock(
            self.repository.root / ".openim-publish.lock", blocking=True, timeout=30
        ):
            group = self.repository.find(self.repository.user_groups(user_id), group_id)
            if group is None:
                raise ValueError("群不存在")
            gid = self.ensure_group(group)
            existing: set[str] = set()
            page = 1
            while True:
                result = self.client.call(
                    "/msg/search_msg",
                    {
                        "recvID": gid,
                        "sessionType": 3,
                        "contentType": 110,
                        "pagination": {"pageNumber": page, "showNumber": 100},
                    },
                )
                logs = result.get("chatLogs") or []
                for item in logs:
                    log = item.get("chatLog") or {}
                    try:
                        existing.add(json.loads(json.loads(log["content"])["data"])["id"])
                    except (KeyError, ValueError, TypeError):
                        continue
                if len(logs) < 100:
                    break
                page += 1
            from app.application.group_chat.projections import ChatProjection

            with sqlite3.connect(self.repository.root / "openim-publication.sqlite3") as ledger:
                ledger.execute(
                    "CREATE TABLE IF NOT EXISTS published (key TEXT PRIMARY KEY, state TEXT NOT NULL)"
                )
            for row in self.repository.read_messages():
                if (
                    int(row.get("user_id") or 0) != user_id
                    or row.get("group_id") != group_id
                    or int(row.get("tenant_id") or 0) != self.tenant
                    or row["id"] in existing
                ):
                    continue
                key = f"{self.client.api}:{self.tenant}:{user_id}:{group_id}:{row['id']}"
                with sqlite3.connect(self.repository.root / "openim-publication.sqlite3") as ledger:
                    state = ledger.execute(
                        "SELECT state FROM published WHERE key=?", (key,)
                    ).fetchone()
                    if state and state[0] == "sent":
                        continue
                    if state:
                        # Search may lag behind an accepted send. Never replay an ambiguous send.
                        raise OpenIMError("消息投递结果待核对，请勿重复派工")
                sender = (
                    self.identity(user_id, "u")
                    if row["role"] == "user"
                    else self.identity(user_id, "e", row["sender_id"])
                )
                if row["role"] != "user" and row["sender_id"] not in {
                    m["employee_id"] for m in group.get("members", [])
                }:
                    known = self.client.call("/user/get_users_info", {"userIDs": [sender]})
                    if not known.get("usersInfo"):
                        self.client.call(
                            "/user/user_register",
                            {
                                "users": [
                                    {
                                        "userID": sender,
                                        "nickname": row["sender_name"],
                                        "faceURL": "",
                                    }
                                ]
                            },
                        )
                public = ChatProjection.public_message(row)
                with sqlite3.connect(self.repository.root / "openim-publication.sqlite3") as ledger:
                    ledger.execute("INSERT INTO published VALUES (?, 'pending')", (key,))
                self.client.call(
                    "/msg/send_msg",
                    {
                        "sendID": sender,
                        "groupID": gid,
                        "recvID": "",
                        "sessionType": 3,
                        "senderNickname": row["sender_name"],
                        "senderFaceURL": "",
                        "senderPlatformID": 10,
                        "contentType": 110,
                        "content": {
                            "data": json.dumps(public, ensure_ascii=False),
                            "description": public["body"][:120],
                            "extension": "xcagi-group-v1",
                        },
                        "isOnlineOnly": False,
                        "notOfflinePush": True,
                    },
                )
                with sqlite3.connect(self.repository.root / "openim-publication.sqlite3") as ledger:
                    ledger.execute("UPDATE published SET state='sent' WHERE key=?", (key,))
                existing.add(row["id"])
            return gid

    def session(self, user_id: int, group_id: str) -> dict:
        gid = self.sync(user_id, group_id)
        user = self.identity(user_id, "u")
        token = self.client.call("/auth/get_user_token", {"userID": user, "platformID": 5})
        group = self.repository.find(self.repository.user_groups(user_id), group_id)
        senders = {
            self.identity(user_id, "e", m["employee_id"]): m["employee_id"]
            for m in group["members"]
        }
        for row in self.repository.read_messages():
            if (
                row.get("group_id") == group_id
                and row.get("user_id") == user_id
                and row.get("tenant_id") == self.tenant
                and row.get("role") != "user"
            ):
                senders[self.identity(user_id, "e", row["sender_id"])] = row["sender_id"]
        senders[user] = "user"
        return {
            "enabled": True,
            "groupID": gid,
            "userID": user,
            "token": token["token"],
            "platformID": 5,
            "senders": senders,
            "groups": {
                self.identity(user_id, "g", str(g["id"])): str(g["id"])
                for g in self.repository.user_groups(user_id)
            },
            "apiAddr": os.environ["XCAGI_OPENIM_PUBLIC_API"],
            "wsAddr": os.environ["XCAGI_OPENIM_PUBLIC_WS"],
        }
