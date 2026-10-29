"""A13: real JSONL, file locks and independent workers; no real side effects."""
from dataclasses import replace
import json
import multiprocessing as mp
import os
import queue

import pytest

from retort_engine.employee_queue import RetortEmployeeQueue, parse_employee_task_result
from retort_engine.models import ImprovementTask
from retort_engine.runtime_adapter import RetortEmployeeRuntimeAdapter


def task(task_id='same-logical-task'):
    return ImprovementTask(task_id,'synthetic','verification','why','action','accept')


def test_repeated_submission_has_one_record_and_one_hook(tmp_path):
    calls = []
    adapter = RetortEmployeeRuntimeAdapter(tmp_path/'queue.jsonl', dispatch_hook=calls.append)
    first = adapter.submit_tasks([task()], source='audit')[0]
    second = adapter.submit_tasks([task()], source='audit')[0]
    assert first.queue_id == second.queue_id
    assert len(adapter.queue.load()) == len(calls) == 1
    assert adapter.queue.load()[0]['status'] == 'dispatched'


def _submit_worker(path, barrier, events):
    adapter = RetortEmployeeRuntimeAdapter(path, dispatch_hook=lambda record: events.put(('dispatch',record.queue_id)))
    barrier.wait(timeout=10)
    for _ in range(20):
        adapter.submit_tasks([task()], source='audit')
    events.put(('done',os.getpid()))


@pytest.mark.parametrize('method', [name for name in ('spawn','fork') if name in mp.get_all_start_methods()])
def test_cross_process_replays_are_deduplicated(tmp_path, method):
    context=mp.get_context(method)
    barrier, events=context.Barrier(2),context.Queue()
    path=tmp_path/'queue.jsonl'
    processes=[context.Process(target=_submit_worker,args=(str(path),barrier,events)) for _ in range(2)]
    for process in processes: process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    records=[]
    while True:
        try: records.append(events.get(timeout=0.2))
        except queue.Empty: break
    assert sum(record[0]=='dispatch' for record in records)==1, records
    assert sum(record[0]=='done' for record in records)==2
    assert len(RetortEmployeeQueue(path).load())==1


def test_hook_exception_is_not_automatically_repeated_after_restart(tmp_path):
    calls=[]
    def hook(record):
        calls.append(record.queue_id)
        raise RuntimeError('synthetic acknowledgement lost')
    path=tmp_path/'queue.jsonl'
    adapter=RetortEmployeeRuntimeAdapter(path,dispatch_hook=hook)
    with pytest.raises(RuntimeError): adapter.submit_tasks([task()],source='audit')
    restarted=RetortEmployeeRuntimeAdapter(path,dispatch_hook=calls.append)
    restarted.submit_tasks([task()],source='audit')
    assert len(calls)==1
    assert restarted.queue.load()[0]['status']=='dispatch_unknown'


def test_crashed_claim_is_not_reexecuted(tmp_path):
    path=tmp_path/'queue.jsonl'
    original=RetortEmployeeQueue(path)
    record=original.enqueue_employee_task(task(),source='audit')
    original.claim_dispatch(record)
    calls=[]
    restarted=RetortEmployeeRuntimeAdapter(path,dispatch_hook=calls.append)
    restarted.submit_tasks([task()],source='audit')
    assert not calls
    assert restarted.queue.load()[0]['status']=='dispatching'


def test_new_source_is_a_distinct_logical_task(tmp_path):
    calls=[]
    adapter=RetortEmployeeRuntimeAdapter(tmp_path/'q.jsonl',dispatch_hook=calls.append)
    adapter.submit_tasks([task()],source='a')
    adapter.submit_tasks([task()],source='b')
    assert len(calls)==2 and calls[0].queue_id!=calls[1].queue_id


def test_changed_payload_for_existing_identity_is_rejected(tmp_path):
    q=RetortEmployeeQueue(tmp_path/'q.jsonl')
    q.enqueue_employee_task(task(),source='audit')
    with pytest.raises(ValueError,match='different payload'):
        q.enqueue_employee_task(replace(task(),action='different'),source='audit')
    assert len(q.load())==1


def test_legacy_queue_id_and_extra_metadata_are_preserved(tmp_path):
    path=tmp_path/'q.jsonl'
    legacy={'queue_id':'legacy-uuid','task':task().to_dict(),'source':'audit','status':'queued','created_at':'2026-10-29','extra':'keep'}
    path.write_text(json.dumps(legacy)+'\n')
    q=RetortEmployeeQueue(path)
    record=q.enqueue_employee_task(task(),source='audit')
    assert record.queue_id=='legacy-uuid'
    q.claim_dispatch(record)
    assert q.load()[0]['extra']=='keep'


def test_legacy_duplicates_are_not_silently_deleted(tmp_path):
    path=tmp_path/'q.jsonl'
    legacy={'queue_id':'legacy','task':task().to_dict(),'source':'audit','status':'queued'}
    before=json.dumps(legacy)+'\n'+json.dumps({**legacy,'queue_id':'other'})+'\n'
    path.write_text(before)
    with pytest.raises(ValueError,match='reconciliation'):
        RetortEmployeeQueue(path).enqueue_employee_task(task(),source='audit')
    assert path.read_text()==before


def test_write_failure_preserves_existing_queue_and_removes_temp(tmp_path,monkeypatch):
    q=RetortEmployeeQueue(tmp_path/'q.jsonl')
    q.enqueue_employee_task(task(),source='audit')
    before=q.path.read_bytes()
    def fail_replace(*args): raise OSError('synthetic rename failure')
    monkeypatch.setattr(os,'replace',fail_replace)
    with pytest.raises(OSError): q.enqueue_employee_task(task('new'),source='audit')
    assert q.path.read_bytes()==before
    assert not list(tmp_path.glob('*.tmp'))


def test_no_hook_leaves_task_available_for_later_dispatch(tmp_path):
    path=tmp_path/'q.jsonl'
    RetortEmployeeRuntimeAdapter(path).submit_tasks([task()],source='audit')
    calls=[]
    RetortEmployeeRuntimeAdapter(path,dispatch_hook=calls.append).submit_tasks([task()],source='audit')
    assert len(calls)==1


def test_forged_dispatch_payload_cannot_replace_persisted_task(tmp_path):
    q=RetortEmployeeQueue(tmp_path/'q.jsonl')
    record=q.enqueue_employee_task(task(),source='audit')
    with pytest.raises(ValueError,match='does not match'):
        q.claim_dispatch(replace(record,task=replace(task(),action='other')))
    assert q.load()[0]['status']=='queued'


def test_result_parser_stays_compatible():
    result=parse_employee_task_result({'task_id':'t','status':'done','evidence':'e','score_after':{'x':1}})
    assert result.evidence==('e',) and result.score_after=={'x':1.0}
