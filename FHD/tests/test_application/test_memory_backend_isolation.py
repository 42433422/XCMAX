"""Projection adapters authorize stored owners and preserve revision ordering."""

from copy import deepcopy

import pytest

from app.infrastructure.memory import mem0_backend as mod
from tests.fixtures.governed_memory_runtime import owner_id

ALICE = owner_id()
BOB = owner_id(8)


def row(mid, owner=ALICE, mod_id="sales", **meta):
    return {
        "id": mid,
        "user_id": owner,
        "memory": "retained original",
        "metadata": {
            "user_id": owner,
            "mod_id": mod_id,
            "memory_type": "fact",
            "source": "memory_v2",
            "source_owner_id": owner,
            "source_memory_id": f"source-{mid}",
            "source_revision": 2,
            "valid_to": "",
            "superseded_by": "",
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
        self.rows[memory_id].update(memory=text, metadata=deepcopy(metadata))

    def add(self, *, messages, user_id, metadata, infer):
        assert infer is False
        mid = f"created-{len(self.rows)}"
        self.mutations.append(("add", mid))
        self.rows[mid] = {
            "id": mid,
            "user_id": user_id,
            "memory": messages[0]["content"],
            "metadata": deepcopy(metadata),
        }
        return {"results": [{"id": mid}]}

    def get_all(self, *, filters, top_k=20, show_expired=False):
        assert show_expired is True
        # A faulty adapter returning foreign rows must not authorize their mutation.
        return {"results": list(self.rows.values())[:top_k]}

    def delete_all(self, user_id=None):
        self.mutations.append(("delete_all", user_id))
        ids = [mid for mid, r in self.rows.items() if r.get("user_id") == user_id]
        for mid in ids:
            del self.rows[mid]
        return {"deleted_count": len(ids)}


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(tmp_path / "projection-locks"))
    store = Store([row("old"), row("new"), row("foreign", BOB), row("other", mod_id="other")])
    backend = mod.Mem0LongTermMemory()
    monkeypatch.setattr(backend, "_active", lambda: store)
    return backend, store


def test_mixed_ids_delete_only_the_owner_and_requested_mod(service):
    backend, store = service
    assert (
        backend.forget(user_id=ALICE, memory_ids=["foreign", "old", "old", "other"], mod_id="sales")
        == 1
    )
    assert store.mutations == [("delete", "old")]
    assert "foreign" in store.rows and "other" in store.rows


@pytest.mark.parametrize("kwargs", [{"memory_ids": []}, {"mod_id": ""}, {"user_id": ""}])
def test_empty_identifiers_never_expand_into_bulk_deletion(service, kwargs):
    backend, store = service
    assert backend.forget(**{"user_id": ALICE, **kwargs}) == 0
    assert store.mutations == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_memory_id": ""},
        {"user_id": ""},
        {"revision": 0},
        {"revision": True},
        {"text": ""},
        {"text": "  "},
    ],
)
def test_invalid_projection_identifiers_never_mutate_existing_rows(service, kwargs):
    backend, store = service
    request = {
        "user_id": ALICE,
        "source_memory_id": "source-old",
        "revision": 3,
        "text": "new revision",
    }
    assert backend.upsert_governed(**{**request, **kwargs}) is False
    assert store.mutations == []


@pytest.mark.parametrize("revision,text", [(1, "obsolete"), (2, "same revision forgery")])
def test_revision_guard_rejects_stale_and_conflicting_replays(service, revision, text):
    backend, store = service
    assert not backend.upsert_governed(
        user_id=ALICE, source_memory_id="source-old", revision=revision, text=text
    )
    assert store.mutations == []
    assert store.rows["old"]["memory"] == "retained original"


def test_revision_update_changes_only_the_selected_owned_source(service):
    backend, store = service
    before = deepcopy(store.rows)
    assert backend.upsert_governed(
        user_id=ALICE,
        source_memory_id="source-old",
        revision=3,
        text="confirmed correction",
        metadata={"custom": "new governed metadata"},
    )
    assert store.mutations == [("update", "old")]
    current = store.rows["old"]
    assert current["memory"] == "confirmed correction"
    assert current["metadata"]["source_revision"] == 3
    assert current["metadata"]["source_owner_id"] == ALICE
    assert current["metadata"]["source_memory_id"] == "source-old"
    assert all(store.rows[mid] == before[mid] for mid in ("foreign", "new", "other"))


def test_source_identifier_cannot_delete_another_owner_or_another_source(service):
    backend, store = service
    assert backend.forget_source(user_id=ALICE, source_memory_id="source-foreign") == 0
    assert store.mutations == []
    assert backend.forget_source(user_id=ALICE, source_memory_id="source-old") == 1
    assert store.mutations == [("delete", "old")]
    assert set(store.rows) == {"new", "foreign", "other"}


@pytest.mark.parametrize(
    "record",
    [
        {"id": "old", "metadata": {}},
        row("old", user_id=BOB),
        {**row("old"), "id": "different"},
    ],
)
def test_unknown_conflicting_or_wrong_record_identity_is_denied(service, record):
    backend, store = service
    store.rows["old"] = record
    assert backend.forget(user_id=ALICE, memory_ids=["old"]) == 0
    assert store.mutations == []


def test_mod_deletion_does_not_touch_other_mods_or_users(service):
    backend, store = service
    assert backend.forget(user_id=ALICE, mod_id="sales") == 2
    assert set(store.rows) == {"foreign", "other"}
    assert all(op != "delete_all" for op, _ in store.mutations)


def test_explicit_user_bulk_deletion_retains_other_users(service):
    backend, store = service
    assert backend.forget(user_id=ALICE) == 3
    assert set(store.rows) == {"foreign"}


@pytest.mark.parametrize("operation", ["update", "add"])
def test_sdk_internal_type_error_is_not_retried(service, monkeypatch, operation):
    backend, store = service
    calls = []

    def broken(*args, **kwargs):
        calls.append((args, kwargs))
        raise TypeError("internal SDK bug, not keyword rejection")

    monkeypatch.setattr(store, operation, broken)
    with pytest.raises(TypeError, match="internal SDK bug"):
        backend.upsert_governed(
            user_id=ALICE,
            source_memory_id="source-old" if operation == "update" else "new-source",
            revision=3,
            text="confirmed new value",
        )
    assert len(calls) == 1
    assert store.rows["old"]["memory"] == "retained original"


def test_failed_projection_update_preserves_stored_data_and_reports_retry(service, monkeypatch):
    backend, store = service
    before = deepcopy(store.rows)

    def unavailable(*args, **kwargs):
        raise OSError("projection disk unavailable")

    monkeypatch.setattr(store, "update", unavailable)
    assert not backend.upsert_governed(
        user_id=ALICE, source_memory_id="source-old", revision=3, text="new"
    )
    assert store.rows == before and store.mutations == []


def test_unconfirmed_sdk_add_result_does_not_delete_existing_projection(service, monkeypatch):
    backend, store = service
    before = deepcopy(store.rows)
    monkeypatch.setattr(store, "add", lambda **kwargs: {"results": []})
    assert not backend.upsert_governed(
        user_id=ALICE, source_memory_id="new-source", revision=1, text="new"
    )
    assert store.rows == before and store.mutations == []


def test_mod_deletion_bounds_continuously_growing_pages_without_widening(service, monkeypatch):
    backend, store = service
    pages = []
    monkeypatch.setattr(mod, "_MAX_MOD_DELETE_PAGES", 2)

    def growing_pages(*, filters, top_k=20, show_expired=False):
        pages.append(filters)
        mid = f"incoming-{len(pages)}"
        store.rows[mid] = row(mid)
        return {"results": [store.rows[mid]]}

    monkeypatch.setattr(store, "get_all", growing_pages)
    assert backend.forget(user_id=ALICE, mod_id="sales") == 2
    assert len(pages) == 2
    assert store.mutations == [("delete", "incoming-1"), ("delete", "incoming-2")]
    assert set(store.rows) == {"old", "new", "foreign", "other"}
