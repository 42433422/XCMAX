"""A05/A06: actual SQLite arbitration, synthetic messages, mocked HTTP only."""
import json
import multiprocessing as mp
import os
import queue
from unittest.mock import patch

import httpx
import pytest

from modstore_server import cs_webhook_outbox as outbox


@pytest.fixture(autouse=True)
def isolated_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv('MODSTORE_CS_WEBHOOK_OUTBOX_PATH', str(tmp_path / 'outbox.sqlite'))
    monkeypatch.setenv('MODSTORE_MIGRATE_LEGACY_CS_WEBHOOK_OUTBOX', '0')
    monkeypatch.setattr(outbox.time, 'sleep', lambda _: None)
    outbox.ensure_outbox_schema()


def enqueue(**kwargs):
    return outbox.enqueue_webhook(target_url='https://synthetic.invalid/webhook',
                                  payload={'landing_contact_id':42}, **kwargs)


def row(rid):
    with outbox._connect() as conn:
        return dict(conn.execute('SELECT * FROM cs_webhook_outbox WHERE id=?', (rid,)).fetchone())


@pytest.mark.parametrize('status,body,expected', [
    (200, {'success':True}, True), (201, {'ok':True}, True),
    (200, {'success':False}, False), (200, {'ok':False}, False),
    (200, {'success':True,'ok':False}, False), (200, {'success':1}, False),
    (200, {}, False), (200, [], False), (204, None, False),
    (301, None, False), (302, None, False), (307, None, False), (308, None, False),
    (400, {'success':True}, False), (500, {'success':True}, False),
])
def test_both_delivery_paths_require_channel_receipt(monkeypatch, status, body, expected):
    response = (httpx.Response(status, json=body) if body is not None
                else httpx.Response(status, text='<html>login</html>', headers={'location':'/login'}))
    requests = []
    def send(*args, **kwargs):
        requests.append(kwargs)
        return response
    monkeypatch.setattr(outbox.httpx, 'post', send)
    rid = enqueue()
    assert outbox._deliver_row(row(rid))[0] is expected
    assert outbox.deliver_webhook_with_retry(target_url='https://synthetic.invalid/webhook',
                                            payload={'synthetic':True}, inline_attempts=1) is expected
    assert all(request['follow_redirects'] is False for request in requests)


def _competing_worker(db, barrier, events, manual):
    os.environ['MODSTORE_CS_WEBHOOK_OUTBOX_PATH'] = db
    os.environ['MODSTORE_MIGRATE_LEGACY_CS_WEBHOOK_OUTBOX'] = '0'
    def send(*args, **kwargs):
        events.put(('send', kwargs['headers']['Idempotency-Key'], os.getpid()))
        return httpx.Response(200, json={'success':True})
    with patch.object(outbox.httpx, 'post', send):
        barrier.wait(timeout=10)
        for _ in range(20):
            if manual:
                outbox.replay_outbox_item(1)
            else:
                outbox.process_pending_outbox(limit=1)
    events.put(('done', os.getpid()))


@pytest.mark.parametrize('method', [name for name in ('spawn','fork') if name in mp.get_all_start_methods()])
def test_two_independent_workers_and_manual_replay_send_once(method):
    rid = enqueue()
    assert rid == 1
    context = mp.get_context(method)
    barrier, events = context.Barrier(2), context.Queue()
    db = os.environ['MODSTORE_CS_WEBHOOK_OUTBOX_PATH']
    processes = [context.Process(target=_competing_worker, args=(db,barrier,events,manual))
                 for manual in (False,True)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    records = []
    while True:
        try:
            records.append(events.get(timeout=0.2))
        except queue.Empty:
            break
    assert sum(record[0] == 'send' for record in records) == 1, records
    assert sum(record[0] == 'done' for record in records) == 2
    saved = row(rid)
    assert saved['status'] == 'delivered' and saved['attempts'] == 1


def test_inline_and_background_retry_keep_one_message_identity(monkeypatch):
    keys = []
    def send(*args, **kwargs):
        keys.append(kwargs['headers']['Idempotency-Key'])
        return httpx.Response(403) if len(keys) == 1 else httpx.Response(200, json={'success':True})
    monkeypatch.setattr(outbox.httpx, 'post', send)
    assert not outbox.deliver_webhook_with_retry(target_url='https://synthetic.invalid', payload={}, inline_attempts=1)
    with outbox._connect() as conn:
        conn.execute("UPDATE cs_webhook_outbox SET next_retry_at=NULL")
    assert outbox.process_pending_outbox()['delivered'] == 1
    assert len(keys) == 2 and keys[0] == keys[1]
    assert row(1)['attempts'] == 2
    assert outbox.replay_outbox_item(1)['ok']
    assert len(keys) == 2


def test_ack_timeout_is_not_automatically_redelivered(monkeypatch):
    calls = []
    def send(*args, **kwargs):
        calls.append(kwargs)
        raise httpx.ReadTimeout('synthetic lost ack')
    monkeypatch.setattr(outbox.httpx, 'post', send)
    rid = enqueue()
    outbox.process_pending_outbox()
    assert row(rid)['status'] == 'delivery_unknown'
    outbox.process_pending_outbox()
    assert outbox.replay_outbox_item(rid) == {'ok':False,'error':'delivery_unknown'}
    assert len(calls) == 1
    assert outbox.outbox_status_summary()['delivery_unknown_count'] == 1


@pytest.mark.parametrize('sent', [False,True])
def test_expired_claim_preserves_unknown_outcome_without_second_send(monkeypatch, sent):
    rid = enqueue()
    claimed, status = outbox._claim_outbox_item(rid)
    assert status == 'sending' and row(rid)['attempts'] == 1
    sends = []
    def send(*args, **kwargs):
        sends.append(True)
        return httpx.Response(200, json={'success':True})
    monkeypatch.setattr(outbox.httpx, 'post', send)
    if sent:
        assert outbox._deliver_row(claimed)[0]
    # Simulate process death before a durable acknowledgement, without assuming
    # whether the peer acted. Persisted state is identical in both windows.
    with outbox._connect() as conn:
        conn.execute("UPDATE cs_webhook_outbox SET next_retry_at='2000-01-01T00:00:00+00:00'")
    outbox.process_pending_outbox()
    assert row(rid)['status'] == 'delivery_unknown'
    assert not outbox.replay_outbox_item(rid)['ok']
    assert len(sends) == int(sent)
    assert json.loads(row(rid)['payload_json']) == {'landing_contact_id':42}


def test_late_worker_cannot_overwrite_a_changed_claim(monkeypatch):
    rid = enqueue()
    def deliver(claimed):
        with outbox._connect() as conn:
            conn.execute("UPDATE cs_webhook_outbox SET attempts=attempts+1, status='delivery_unknown' WHERE id=?",(rid,))
        return True, ''
    monkeypatch.setattr(outbox, '_deliver_row', deliver)
    result = outbox._attempt_delivery(rid)
    assert not result['ok']
    assert row(rid)['status'] == 'delivery_unknown'


def test_manual_replay_cannot_compete_with_current_owner(monkeypatch):
    rid = enqueue()
    nested = []
    def send(*args, **kwargs):
        nested.append(outbox.replay_outbox_item(rid))
        return httpx.Response(200, json={'success':True})
    monkeypatch.setattr(outbox.httpx, 'post', send)
    assert outbox._attempt_delivery(rid)['ok']
    assert nested == [{'ok':False,'error':'sending'}]
    assert row(rid)['attempts'] == 1


def test_rejected_attempts_stop_at_configured_budget(monkeypatch):
    rid = enqueue(max_attempts=2)
    monkeypatch.setattr(outbox.httpx, 'post', lambda *a, **k: httpx.Response(403))
    assert outbox._attempt_delivery(rid, ignore_due=True)['status'] == 'pending'
    assert outbox._attempt_delivery(rid, ignore_due=True)['status'] == 'failed'
    assert outbox._attempt_delivery(rid, ignore_due=True)['status'] == 'failed'
    assert row(rid)['attempts'] == 2


@pytest.mark.parametrize('headers', ['[1]', 'null', '{broken', '{"key":1}'])
def test_corrupt_headers_are_quarantined_without_sending(monkeypatch, headers):
    rid = enqueue()
    with outbox._connect() as conn:
        conn.execute('UPDATE cs_webhook_outbox SET headers_json=? WHERE id=?',(headers,rid))
    def forbidden_send(*args, **kwargs):
        raise AssertionError('corrupt headers must not reach transport')
    monkeypatch.setattr(outbox.httpx, 'post', forbidden_send)
    assert outbox._attempt_delivery(rid)['status'] == 'failed'
    assert row(rid)['status'] == 'failed'


def test_already_delivered_is_not_counted_as_a_new_attempt(monkeypatch):
    rid = enqueue()
    monkeypatch.setattr(outbox.httpx, 'post', lambda *a, **k: httpx.Response(200, json={'success':True}))
    assert outbox._attempt_delivery(rid)['attempted']
    result = outbox._attempt_delivery(rid)
    assert result['ok'] and not result['attempted']
    assert row(rid)['attempts'] == 1
