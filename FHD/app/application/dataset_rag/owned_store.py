"""Private mixed-bundle JSON: SQL-authoritative heads and same-attempt publication.

Only the fresh guarded namespace is supported. This does not adopt legacy stores,
replay interrupted effects, start rebuild workers, or infer receipts from rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

from app.application.dataset_rag.store_identity import (
    StoreIdentityError,
    _pairs,
    initialize_new_store,
    read_bound_store,
    valid_store_id,
)
from app.application.workflow.plan_store import OWNED_KNOWLEDGE_CONTROL_KEY as _CONTROL
from app.desktop_runtime import database_generation_registry as generations


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _effect_digest(raw):
    image = deepcopy(raw)
    image["owned_commit"]["receipt"].pop("digest", None)
    return _digest(image)


def knowledge_path(target):
    return target.with_suffix(".knowledge.json")


def _publish(path, payload):
    """Caller holds source and dataset locks; publication is durable, not just replace."""
    fd, temporary = tempfile.mkstemp(prefix=".owned-dataset-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(_json(payload).encode())
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize_mixed_store(conn, target):
    """Enrollment callback runs while source is CLOSED and the lifecycle lock is held."""
    generations._owned_lock(target, None)
    path = knowledge_path(target)
    store_id = initialize_new_store(path)
    raw = read_bound_store(path, store_id)
    raw["owned_commit"] = {"head": str(uuid4()), "receipt": None}
    _publish(path, raw)
    state = {
        "source": asdict(generations.read_owned_source(target, allow_closed=True)),
        "store_id": store_id,
        "head": raw["owned_commit"]["head"],
        "digest": _digest(raw),
        "pending": None,
        "effects": {},
    }
    conn.execute(
        "INSERT INTO workflow_plans(plan_id,user_id,intent,plan_json,runtime_context,status) "
        "VALUES (?,?,?,'{}',?,?)",
        (_CONTROL, "host", _CONTROL, _json(state), _CONTROL),
    )
    conn.commit()


class OwnedKnowledge:
    """Use existing source/session authority; one pending effect blocks unrelated use."""

    def __init__(self, factory):
        if factory.binding.get("protocol") != "etl-owned-mixed-v1":
            raise StoreIdentityError("mixed bundle authority required")
        self.factory = factory
        self.path = knowledge_path(factory.target)
        self.active = None
        with factory.guard():
            self.store_id = self._state()[0]["store_id"]

    def _state(self):
        generations._owned_lock(self.factory.target, None)
        with self.factory() as db:
            rows = (
                db.connection()
                .exec_driver_sql(
                    "SELECT runtime_context FROM workflow_plans WHERE plan_id=? AND "
                    "user_id='host' AND intent=? AND status=?",
                    (_CONTROL, _CONTROL, _CONTROL),
                )
                .fetchall()
            )
        if len(rows) != 1:
            raise StoreIdentityError("owned JSON authority unavailable")
        encoded = rows[0][0]
        try:
            state = json.loads(encoded, object_pairs_hook=_pairs)
            if (
                not isinstance(state, dict)
                or set(state) != {"source", "store_id", "head", "digest", "pending", "effects"}
                or state["source"] != asdict(self.factory.source)
                or not valid_store_id(state["store_id"])
                or not valid_store_id(state["head"])
                or not isinstance(state["digest"], str)
                or len(state["digest"]) != 64
                or not isinstance(state["effects"], dict)
                or len(state["effects"]) > 4096
            ):
                raise ValueError("invalid head")
        except (ValueError, TypeError):
            raise StoreIdentityError("owned JSON authority malformed") from None
        return state, encoded

    def _cas(self, previous, state):
        generations._owned_lock(self.factory.target, None)
        with self.factory() as db:
            changed = (
                db.connection()
                .exec_driver_sql(
                    "UPDATE workflow_plans SET runtime_context=? WHERE plan_id=? "
                    "AND runtime_context=? AND status=?",
                    (_json(state), _CONTROL, previous, _CONTROL),
                )
                .rowcount
            )
            if changed != 1:
                raise StoreIdentityError("owned JSON head compare-and-swap failed")
            db.commit()
            self.factory.validate(db)
            if db.connection().exec_driver_sql(
                "SELECT runtime_context FROM workflow_plans WHERE plan_id=?", (_CONTROL,)
            ).scalar_one() != _json(state):
                raise StoreIdentityError("owned JSON committed head readback changed")

    def validate(self, raw=None):
        state, _ = self._state()
        raw = read_bound_store(self.path, self.store_id) if raw is None else raw
        if raw.get("store_id") != self.store_id:
            raise StoreIdentityError("owned JSON identity changed")
        if state["pending"] is not None and state["pending"] != self.active:
            raise StoreIdentityError("owned JSON effect outcome requires original receipt")
        if (
            self.active is not None
            and raw.get("owned_commit") == {"head": self.active["after"], "receipt": self.active}
            and _effect_digest(raw) == self.active.get("digest")
        ):
            return raw
        if (
            _digest(raw) != state["digest"]
            or raw.get("owned_commit", {}).get("head") != state["head"]
        ):
            raise StoreIdentityError("owned JSON snapshot is not the authoritative head")
        return raw

    def _attempt(self, attempt):
        if (
            not isinstance(attempt, dict)
            or set(attempt)
            != {"source", "plan_digest", "batch_id", "operation_id", "direction", "nonce"}
            or attempt["source"] != self.factory.binding
            or attempt["direction"] not in {"execute", "rollback"}
            or not valid_store_id(attempt["nonce"])
            or any(
                not isinstance(attempt[k], str) or not attempt[k]
                for k in ("plan_digest", "batch_id", "operation_id")
            )
        ):
            raise StoreIdentityError("original immutable effect identity required")
        return _digest(attempt)

    @contextmanager
    def effect(self, repository, attempt):
        key = self._attempt(attempt)
        if (
            self.active is not None
            or repository.owned_guard is not self
            or repository.storage_path != self.path
        ):
            raise StoreIdentityError("owned JSON repository binding changed")
        state, encoded = self._state()
        self.validate()
        if key in state["effects"] or len(state["effects"]) >= 4096:
            raise StoreIdentityError("effect replay or journal limit")
        pending = {
            "attempt": deepcopy(attempt),
            "before": state["head"],
            "after": str(uuid4()),
            "digest": None,
        }
        state["pending"] = pending
        self._cas(encoded, state)
        self.active = pending
        proof = {}
        try:
            yield proof
            # A retained/skip operation still needs a durable same-attempt receipt.
            raw = read_bound_store(self.path, self.store_id)
            if raw.get("owned_commit", {}).get("head") == pending["before"]:
                with repository.lock:
                    repository._persist_locked()
            proof.update(self.finish_same_attempt(attempt))
        finally:
            self.active = None

    def persist(self, repository, payload):
        if self.active is None or repository.lock.connection is None:
            raise StoreIdentityError("owned JSON mutation has no original pending intent")
        self.validate()
        state, encoded = self._state()
        if state["pending"] != self.active or self.active["digest"] is not None:
            raise StoreIdentityError("one publication per original effect required")
        payload["owned_commit"] = {"head": self.active["after"], "receipt": deepcopy(self.active)}
        self.active = {**self.active, "digest": _effect_digest(payload)}
        state["pending"] = self.active
        self._cas(encoded, state)
        payload["owned_commit"]["receipt"] = deepcopy(self.active)
        _publish(self.path, payload)

    def observe_same_attempt(self, attempt):
        """Read-only proof before the coordinator verifies every original business image."""
        key = self._attempt(attempt)
        state, _ = self._state()
        pending = state["pending"]
        raw = read_bound_store(self.path, self.store_id)
        if pending is None:
            self.validate(raw)
            proof = self.verify_effect(attempt)
            if state["head"] != proof.get("after") or state["digest"] != proof.get(
                "published_digest"
            ):
                raise StoreIdentityError("later JSON head cannot finalize an earlier attempt")
            return proof, raw
        if (
            not isinstance(pending, dict)
            or pending.get("attempt") != attempt
            or pending.get("before") != state["head"]
            or not valid_store_id(pending.get("after"))
            or raw.get("owned_commit") != {"head": pending["after"], "receipt": pending}
            or _effect_digest(raw) != pending.get("digest")
            or key in state["effects"]
        ):
            raise StoreIdentityError("same-attempt JSON receipt unavailable; no replay")
        proof = {**pending, "published_digest": _digest(raw)}
        return proof, raw

    def finish_same_attempt(self, attempt):
        proof, raw = self.observe_same_attempt(attempt)
        state, encoded = self._state()
        pending = state["pending"]
        if pending is None:
            return proof
        # A previous publisher may have died after replace but before directory fsync.
        for path, flags in ((self.path, 0), (self.path.parent, os.O_DIRECTORY)):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | flags)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        if read_bound_store(self.path, self.store_id) != raw:
            raise StoreIdentityError("owned JSON changed during durable acknowledgement")
        key = self._attempt(attempt)
        state.update(head=pending["after"], digest=proof["published_digest"], pending=None)
        state["effects"][key] = proof
        self._cas(encoded, state)
        return deepcopy(proof)

    def verify_effect(self, attempt):
        key = self._attempt(attempt)
        self.validate()
        proof = self._state()[0]["effects"].get(key)
        if not isinstance(proof, dict) or proof.get("attempt") != attempt:
            raise StoreIdentityError("original effect receipt unavailable")
        return deepcopy(proof)
