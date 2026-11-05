"""File event records use private runtime storage for every path source."""

import json
import tempfile

import pytest

from modstore_server.eventing.events import new_event
from modstore_server.eventing.outbox import FileEventOutbox


def test_default_records_are_outside_source(monkeypatch, tmp_path):
    monkeypatch.delenv("MODSTORE_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("MODSTORE_EVENT_OUTBOX_PATH", raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    outbox = FileEventOutbox()
    assert outbox.path == tmp_path / "modstore_runtime" / "event_outbox.jsonl"
    event = new_event("payment.paid", producer="test", subject_id="synthetic-order")
    outbox.append(event)
    assert json.loads(outbox.path.read_text()) == event.to_dict()


@pytest.mark.parametrize("path_source", ["argument", "file_env", "runtime_env"])
def test_source_checkout_destinations_are_rejected(monkeypatch, tmp_path, path_source):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.delenv("MODSTORE_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("MODSTORE_EVENT_OUTBOX_PATH", raising=False)
    destination = checkout / "private" / "event_outbox.jsonl"
    if path_source == "file_env":
        monkeypatch.setenv("MODSTORE_EVENT_OUTBOX_PATH", str(destination))
    elif path_source == "runtime_env":
        monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(destination.parent))
    with pytest.raises(ValueError, match="Git checkout"):
        FileEventOutbox(destination if path_source == "argument" else None)
    assert not destination.parent.exists()


def test_file_symlink_cannot_redirect_records_into_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").write_text("gitdir: /synthetic-worktree\n")
    destination = checkout / "events.jsonl"
    destination.write_text("synthetic-existing-record\n")
    alias = tmp_path / "external-events.jsonl"
    alias.symlink_to(destination)
    with pytest.raises(ValueError, match="Git checkout"):
        FileEventOutbox(alias)
    assert destination.read_text() == "synthetic-existing-record\n"


def test_explicit_external_file_preserves_path_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    configured = tmp_path / "configured" / "events.jsonl"
    monkeypatch.setenv("MODSTORE_EVENT_OUTBOX_PATH", str(configured))
    assert FileEventOutbox().path == configured
    explicit = tmp_path / "explicit" / "events.jsonl"
    assert FileEventOutbox(explicit).path == explicit
    assert not (tmp_path / "runtime").exists()
