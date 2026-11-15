"""Memory adapters must authorize stored identities before any mutation."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.infrastructure.memory import mem0_backend as mod
from app.infrastructure.memory.consolidation import consolidate


def row(mid, owner="alice", mod_id="sales", **meta):
    return {
        "id": mid,
        "user_id": owner,
        "memory": "retained original",
        "metadata": {
            "mod_id": mod_id,
            "memory_type": "fact",
            "fact_key": "budget",
            "custom": "keep",
            **meta,
        },
    }


class Store:
    def __init__(self, rows):
        self.rows = {r["id"]: deepcopy(r) for r in rows}
        self.mutations = []

    def get(self, mid):
        return deepcopy(self.rows.get(mid))

    def delete(self, mid):
        self.mutations.append(("delete", mid))
        del self.rows[mid]

    def update(self, memory_id, text=None, metadata=None):
        self.mutations.append(("update", memory_id))
        self.rows[memory_id].update(memory=text, metadata=metadata)

    def get_all(self, *, filters, top_k=20, show_expired=False):
        assert show_expired is True
        # A faulty adapter returning foreign records must still be harmless.
        return {"results": list(self.rows.values())[:top_k]}

    def delete_all(self, user_id=None):
        self.mutations.append(("delete_all", user_id))
        ids = [mid for mid, r in self.rows.items() if r.get("user_id") == user_id]
        for mid in ids:
            del self.rows[mid]
        return {"deleted_count": len(ids)}


@pytest.fixture
def service(monkeypatch):
    store = Store([row("old"), row("new"), row("foreign", "bob"), row("other", mod_id="other")])
    backend = mod.Mem0LongTermMemory()
    monkeypatch.setattr(backend, "_active", lambda: store)
    return backend, store


def test_mixed_ids_delete_only_the_owner_and_requested_mod(service):
    backend, store = service
    assert (
        backend.forget(
            user_id="alice", memory_ids=["foreign", "old", "old", "other"], mod_id="sales"
        )
        == 1
    )
    assert store.mutations == [("delete", "old")]
    assert "foreign" in store.rows and "other" in store.rows


@pytest.mark.parametrize("kwargs", [{"memory_ids": []}, {"mod_id": ""}, {"user_id": ""}])
def test_empty_identifiers_never_expand_into_bulk_deletion(service, kwargs):
    backend, store = service
    assert backend.forget(**{"user_id": "alice", **kwargs}) == 0
    assert store.mutations == []


@pytest.mark.parametrize(
    "mid,new_id",
    [("foreign", "new"), ("old", "foreign"), ("old", ""), ("old", "old"), ("missing", "new")],
)
def test_supersede_rejects_foreign_missing_and_self_replacements(service, mid, new_id):
    backend, store = service
    assert (
        backend.supersede_fact("alice", mid, content="injected", new_id=new_id, today="2026-11-15")
        is False
    )
    assert store.mutations == []


@pytest.mark.parametrize(
    "record",
    [
        {"id": "old", "metadata": {}},
        row("old", user_id="bob"),
        {**row("old"), "id": "different"},
    ],
)
def test_unknown_conflicting_or_wrong_record_identity_is_denied(service, record):
    backend, store = service
    store.rows["old"] = record
    assert backend.forget(user_id="alice", memory_ids=["old"]) == 0
    assert store.mutations == []


def test_supersede_preserves_old_content_and_all_existing_metadata(service):
    backend, store = service
    assert backend.supersede_fact(
        "alice", "old", content="untrusted stale text", new_id="new", today="2026-11-15"
    )
    assert store.rows["old"]["memory"] == "retained original"
    meta = store.rows["old"]["metadata"]
    assert meta["valid_to"] == "2026-11-15" and meta["superseded_by"] == "new"
    assert meta["custom"] == "keep" and meta["fact_key"] == "budget"
    assert store.rows["new"]["metadata"].get("valid_to") is None


def test_mod_deletion_does_not_touch_other_mods_or_users(service):
    backend, store = service
    assert backend.forget(user_id="alice", mod_id="sales") == 2
    assert set(store.rows) == {"foreign", "other"}
    assert all(op != "delete_all" for op, _ in store.mutations)


def test_explicit_user_bulk_deletion_retains_other_users(service):
    backend, store = service
    assert backend.forget(user_id="alice") == 3
    assert set(store.rows) == {"foreign"}


def test_sdk_internal_type_error_is_not_retried(service, monkeypatch):
    backend, store = service
    calls = []

    def update(memory_id, text=None, metadata=None):
        calls.append(memory_id)
        raise TypeError("internal SDK bug, not keyword rejection")

    monkeypatch.setattr(store, "update", update)
    with pytest.raises(TypeError, match="internal SDK bug"):
        backend.supersede_fact("alice", "old", content="", new_id="new", today="2026-11-15")
    assert calls == ["old"]


def test_failed_replacement_never_invalidates_existing_fact():
    writes = []
    store = SimpleNamespace(
        search_facts=lambda *a, **kw: [
            {
                "chunk_id": "old",
                "content": "old",
                "metadata": {"fact_key": "budget", "fact_value": "old"},
            }
        ],
        add_fact=lambda *a, **kw: None,
        supersede_fact=lambda *a, **kw: writes.append(kw),
    )
    result = consolidate(store, user_id="alice", facts=[{"key": "budget", "value": "new"}])
    assert result[0]["action"] == "SKIPPED" and result[0]["reason"] == "add_unconfirmed"
    assert writes == []
