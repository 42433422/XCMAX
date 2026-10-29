"""Transactional accounting, interrupted migration and rollback compatibility."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.infrastructure.billing import model_usage as usage


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(path))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "local")
    monkeypatch.setenv("MODEL_USAGE_WALLET_REQUIRED", "1")
    return path


def legacy_entry(key="old", cost=5):
    return {
        "usage_key": key,
        "usage_id": key,
        "user_id": "u",
        "entry_type": "model_call",
        "cost_units": cost,
        "total_tokens": 10,
        "created_at": "2026-01-01",
        "billing_source": "local_model_wallet",
        "billing_status": "debited",
        "wallet_debit": {"status": "debited"},
    }


def seed(path):
    state = {"entries": [legacy_entry()], "wallets": {"u": {"user_id": "u", "balance_units": 95}}}
    path.write_text(json.dumps(state), encoding="utf-8")
    return state


def test_json_migrates_once_and_downgrade_reupgrade_preserves_new_balance(ledger):
    original = seed(ledger)
    assert usage.get_model_wallet("u")["balance_units"] == 95
    assert not ledger.exists()
    backups = list(ledger.parent.glob("*.legacy.json"))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == original
    usage.record_model_usage(user_id="u", usage_key="new", cost_units=7)
    assert usage.get_model_wallet("u")["balance_units"] == 88
    assert usage.record_model_usage(user_id="u", usage_key="old", cost_units=999)["cost_units"] == 5
    usage.export_model_usage_ledger(ledger, retire_database=True)
    assert not usage.model_usage_database_path().exists()
    assert len(list(ledger.parent.glob("*.rollback-*.sqlite3"))) == 1
    downgraded = json.loads(ledger.read_text())
    assert downgraded["wallets"]["u"]["balance_units"] == 88
    # The previous binary adds a charge after rollback, then the new binary upgrades again.
    downgraded["wallets"]["u"]["balance_units"] -= 8
    downgraded["entries"].append(legacy_entry("after-rollback", 8))
    ledger.write_text(json.dumps(downgraded), encoding="utf-8")
    assert usage.get_model_wallet("u")["balance_units"] == 80
    assert len(usage.list_model_usage_entries()) == 3
    assert len(list(ledger.parent.glob("*.legacy.json"))) == 2
    assert usage._load_usage_state()["summary"]["cost_units_total"] == 20


def test_failed_migration_rolls_back_and_retry_does_not_debit_or_duplicate(ledger, monkeypatch):
    seed(ledger)
    save = usage._save_entry

    def fail_after_insert(*args, **kwargs):
        save(*args, **kwargs)
        raise OSError("injected migration failure")

    monkeypatch.setattr(usage, "_save_entry", fail_after_insert)
    with pytest.raises(OSError):
        usage.get_model_wallet("u")
    assert ledger.exists() and not list(ledger.parent.glob("*.legacy.json"))
    monkeypatch.setattr(usage, "_save_entry", save)
    assert usage.get_model_wallet("u")["balance_units"] == 95
    assert len(usage.list_model_usage_entries()) == 1


def test_committed_migration_archive_interruption_is_reentrant(ledger, monkeypatch):
    seed(ledger)
    replace = usage.os.replace
    monkeypatch.setattr(
        usage.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("archive interrupted"))
    )
    with pytest.raises(OSError):
        usage.get_model_wallet("u")
    monkeypatch.setattr(usage.os, "replace", replace)
    assert usage.get_model_wallet("u")["balance_units"] == 95
    assert len(usage.list_model_usage_entries()) == 1 and not ledger.exists()


def test_concurrent_process_first_open_migrates_and_archives_once(ledger):
    seed(ledger)
    code = "from app.infrastructure.billing.model_usage import record_model_usage; record_model_usage(user_id='u',usage_key='cold-process',cost_units=9)"
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(4)
    ]
    for child in children:
        _, error = child.communicate(timeout=15)
        assert child.returncode == 0, error
    assert usage.get_model_wallet("u")["balance_units"] == 86
    assert len(usage.list_model_usage_entries()) == 2
    assert len(list(ledger.parent.glob("*.legacy.json"))) == 1 and not ledger.exists()


def test_corrupt_migration_or_missing_migrated_database_never_becomes_empty_wallet(ledger):
    ledger.write_text("broken JSON", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        usage.get_model_wallet("u")
    seed(ledger)
    assert usage.get_model_wallet("u")["balance_units"] == 95
    usage.model_usage_database_path().unlink()
    with pytest.raises(RuntimeError, match="missing"):
        usage.get_model_wallet("u")


def test_transaction_failure_cannot_leave_partial_wallet_debit(ledger):
    usage.set_model_wallet_balance("u", 100)
    with usage._usage_db(write=True) as db:
        db.execute(
            "CREATE TRIGGER reject_usage BEFORE INSERT ON entries BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        usage.record_model_usage(user_id="u", usage_key="fail", cost_units=7)
    assert usage.get_model_wallet("u")["balance_units"] == 100
    assert usage.list_model_usage_entries() == []


def test_threads_and_processes_share_usage_key_and_refund_idempotency(ledger):
    usage.set_model_wallet_balance("u", 100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(
            pool.map(
                lambda _: usage.record_model_usage(user_id="u", usage_key="thread", cost_units=7),
                range(24),
            )
        )
    assert len({row["usage_id"] for row in entries}) == 1
    code = "from app.infrastructure.billing.model_usage import record_model_usage; record_model_usage(user_id='u',usage_key='process',cost_units=9)"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: subprocess.run(
                    [sys.executable, "-c", code],
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True,
                    timeout=15,
                ),
                range(4),
            )
        )
    assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
    assert usage.get_model_wallet("u")["balance_units"] == 84
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: usage.refund_tool_usage(usage_key="process"), range(24)))
    assert usage.get_model_wallet("u")["balance_units"] == 93
    summary = usage._load_usage_state()["summary"]
    assert summary["entry_count"] == 2 and summary["refund_entry_count"] == 1


def test_hot_append_and_duplicate_lookup_do_not_reload_or_scan_history(ledger, monkeypatch):
    state = {"entries": [legacy_entry(str(n)) for n in range(1000)], "wallets": {}}
    ledger.write_text(json.dumps(state), encoding="utf-8")
    usage.get_model_wallet("u")
    monkeypatch.setattr(
        usage, "_load_legacy_usage_state", lambda **_: pytest.fail("hot-path legacy read")
    )
    summarize = usage._usage_summary

    def bounded_summary(entries):
        assert len(entries) <= 1
        return summarize(entries)

    monkeypatch.setattr(usage, "_usage_summary", bounded_summary)
    usage.record_model_usage(user_id="u", usage_key="new", cost_units=1)
    assert usage.record_model_usage(usage_key="0")["usage_id"] == "0"
    with usage._usage_db() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM entries WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
            ("u",),
        ).fetchall()
    assert any("usage_user_id_created_at" in str(row) for row in plan)


def test_market_success_local_failure_replays_same_owner_amount_and_remote_key(ledger, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    charged, calls = {}, []

    def remote(**kwargs):
        calls.append(kwargs)
        charged.setdefault(kwargs["usage_key"], kwargs["cost_units"])
        return "debited", {"status": "debited", "hold_no": "hold", "amount_yuan": "0.07"}

    monkeypatch.setattr(usage, "_apply_market_wallet_debit", remote)
    save = usage._save_entry

    def crash(db, entry, **kwargs):
        if kwargs.get("state", "complete") == "complete":
            raise OSError("crash after remote success")
        save(db, entry, **kwargs)

    monkeypatch.setattr(usage, "_save_entry", crash)
    with pytest.raises(OSError):
        usage.record_model_usage(user_id="u", usage_key="remote", cost_units=7)
    with pytest.raises(RuntimeError, match="Pending"):
        usage.export_model_usage_ledger(ledger, retire_database=True)
    monkeypatch.setattr(usage, "_save_entry", save)
    result = usage.record_model_usage(user_id="other", usage_key="remote", cost_units=999)
    assert result["user_id"] == "u" and result["cost_units"] == 7
    assert calls[0] == calls[1] and charged == {"remote": 7}
    assert usage._load_usage_state()["summary"]["entry_count"] == 1


@pytest.mark.parametrize("endpoint", ["preauthorize", "settle"])
@pytest.mark.parametrize("fault", ["timeout", "503", "malformed"])
def test_market_unknown_http_outcome_reconciles_frozen_request_before_refund_or_handoff(
    ledger, monkeypatch, endpoint, fault
):
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "original-test-credential")
    monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "https://original-market.test")
    monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "0.01")
    monkeypatch.setenv("MODEL_USAGE_MARKET_MIN_CHARGE", "0.01")
    calls, charges, refunds = [], {}, {}
    inject_fault = True
    refund_timeout = True

    def remote(request):
        nonlocal inject_fault, refund_timeout
        operation = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content)
        calls.append((str(request.url), payload))
        if operation == "settle":
            charges.setdefault(payload["idempotency_key"], payload["actual_amount"])
        if operation == "refund":
            refunds.setdefault(payload["idempotency_key"], payload["refund_amount"])
            if refund_timeout:
                refund_timeout = False
                raise httpx.ReadTimeout("response lost after refund", request=request)
        if inject_fault and operation == endpoint:
            inject_fault = False
            if fault == "timeout":
                raise httpx.ReadTimeout("response lost after commit", request=request)
            if fault == "503":
                return httpx.Response(503, json={"message": "upstream reply lost"})
            return httpx.Response(200, text="incomplete reply")
        return httpx.Response(
            200, json={"hold": {"hold_no": "H"}, "balance": "9.93", "refund": {"id": "R"}}
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        usage.httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(remote), **kwargs),
    )
    first = usage.record_model_usage(user_id="u", usage_key="remote-http", cost_units=7)
    assert first["billing_status"] == "market_debit_pending"
    assert first["wallet_debit"]["outcome_unknown"]
    assert usage.refund_tool_usage(usage_key="remote-http")["refund_status"] == "debit_pending"
    with pytest.raises(RuntimeError, match="Pending market debits"):
        usage.export_model_usage_ledger(ledger, retire_database=True)
    count = len(calls)
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "other-account")
    changed = usage.record_model_usage(user_id="other", usage_key="remote-http", cost_units=999)
    assert changed["billing_status"] == "market_debit_pending" and len(calls) == count
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "original-test-credential")
    monkeypatch.setenv("MODEL_USAGE_MARKET_BASE_URL", "https://different-market.test")
    monkeypatch.setenv("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT", "100.00")
    recovered = usage.record_model_usage(user_id="other", usage_key="remote-http", cost_units=999)
    assert recovered["billing_status"] == "debited" and recovered["user_id"] == "u"
    assert recovered["cost_units"] == 7 and charges == {"remote-http:settle": "0.07"}
    assert all(url.startswith("https://original-market.test/") for url, _ in calls)
    assert all(
        payload["amount"] == "0.07" for url, payload in calls if url.endswith("preauthorize")
    )
    assert (
        len({payload["idempotency_key"] for url, payload in calls if url.endswith("preauthorize")})
        == 1
    )
    assert (
        usage.refund_tool_usage(usage_key="remote-http", refund_key="refund-once")["refund_status"]
        == "refund_pending"
    )
    with pytest.raises(RuntimeError, match="Pending market refunds"):
        usage.export_model_usage_ledger(ledger, retire_database=True)
    assert (
        usage.refund_tool_usage(usage_key="remote-http", refund_key="different")["refund_status"]
        == "refunded"
    )
    assert refunds == {"refund-once": "0.07"}
    usage.export_model_usage_ledger(ledger, retire_database=True)
    assert json.loads(ledger.read_text())["entries"][0]["refund_status"] == "refunded"


def test_known_market_rejection_is_not_an_uncertain_charge(ledger, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setenv("MODEL_USAGE_MARKET_AUTH_TOKEN", "test-credential")
    client_type = httpx.Client
    monkeypatch.setattr(
        usage.httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(402, json={"message": "余额不足"})
            ),
            **kwargs,
        ),
    )
    result = usage.record_model_usage(user_id="u", usage_key="rejected", cost_units=7)
    assert result["billing_status"] == "insufficient_balance"
    assert usage.refund_tool_usage(usage_key="rejected")["refund_status"] == "not_charged"
    usage.export_model_usage_ledger(ledger, retire_database=True)


def test_market_wait_does_not_hold_database_writer_or_global_usage_lock(ledger, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    entered, release = threading.Event(), threading.Event()

    def remote(**_):
        entered.set()
        assert release.wait(3)
        return "debited", {"status": "debited"}

    monkeypatch.setattr(usage, "_apply_market_wallet_debit", remote)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(usage.record_model_usage, usage_key="slow", user_id="u", cost_units=1)
        try:
            assert entered.wait(1)
            assert usage.set_model_wallet_balance("other", 100)["balance_units"] == 100
            monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
            assert usage.record_model_usage(usage_key="fast", cost_units=1)["usage_key"] == "fast"
            assert not pending.done()
        finally:
            release.set()
        pending.result(timeout=2)


def test_pending_refund_and_failed_export_preserve_active_database(ledger, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "market")
    monkeypatch.setattr(
        usage,
        "_apply_market_wallet_debit",
        lambda **_: ("debited", {"status": "debited", "hold_no": "H"}),
    )
    monkeypatch.setattr(usage, "_apply_market_wallet_refund", lambda **_: ("refund_pending", {}))
    usage.record_model_usage(user_id="u", usage_key="k", cost_units=1)
    usage.refund_tool_usage(usage_key="k")
    with pytest.raises(RuntimeError, match="refunds"):
        usage.export_model_usage_ledger(ledger, retire_database=True)
    assert not ledger.exists() and usage.model_usage_database_path().is_file()
    monkeypatch.setattr(usage, "_apply_market_wallet_refund", lambda **_: ("refunded", {}))
    usage.refund_tool_usage(usage_key="k")
    ledger.write_text("existing export", encoding="utf-8")
    monkeypatch.setattr(
        usage.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed"))
    )
    with pytest.raises(OSError):
        usage.export_model_usage_ledger(ledger, retire_database=True)
    assert ledger.read_text() == "existing export" and usage.model_usage_database_path().is_file()


def test_export_cli_handoff_round_trip(ledger):
    from app.infrastructure.billing.model_usage_export import main

    usage.set_model_wallet_balance("u", 123)
    assert main(["--ledger", str(ledger), "--output", str(ledger), "--handoff"]) == 0
    assert json.loads(ledger.read_text())["wallets"]["u"]["balance_units"] == 123
    assert usage.get_model_wallet("u")["balance_units"] == 123


@pytest.mark.parametrize("body", [{"entries": "corrupt"}, {"wallets": []}, {"entries": [42]}])
def test_malformed_legacy_shapes_fail_closed(ledger, body):
    ledger.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed"):
        usage.get_model_wallet("u")
    assert ledger.exists() and not list(ledger.parent.glob("*.legacy.json"))


def test_desktop_locator_is_atomic_once_per_path_and_not_written_for_bad_migration(
    ledger, monkeypatch
):
    data_root = ledger.parent / "desktop"
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setattr(usage, "get_app_data_dir", lambda: str(data_root))
    monkeypatch.setattr(usage, "_storage_location", None)
    marker = data_root / "data" / "model_usage_storage.json"
    ledger.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError):
        usage.get_model_wallet("u")
    assert not marker.exists()
    ledger.write_text('{"entries": [], "wallets": {}}', encoding="utf-8")
    usage.set_model_wallet_balance("u", 100)
    assert json.loads(marker.read_text()) == {"version": 1, "ledger_path": str(ledger.resolve())}
    stamp = marker.stat().st_mtime_ns
    usage.record_model_usage(user_id="u", usage_key="1", cost_units=1)
    usage.record_model_usage(user_id="u", usage_key="2", cost_units=1)
    assert marker.stat().st_mtime_ns == stamp
    other = ledger.parent / "custom.json"
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(other))
    usage.get_model_wallet("u")
    assert json.loads(marker.read_text())["ledger_path"] == str(other.resolve())
