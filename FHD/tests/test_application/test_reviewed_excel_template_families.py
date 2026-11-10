from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.application import reviewed_excel_template_families as families
from app.application.elt.errors import ReviewedExcelError


def source():
    book = Workbook()
    book.active.title = 'S'
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def test_template_families_keep_every_source_once(monkeypatch):
    slices = [{'fragments': [{'sheet': 'S', 'range': f'A{i}:B{i}'}]} for i in range(1, 4)]
    cells = [{'sheet': 'S', 'cell': f'A{i}', 'value': '标题', 'kind': 'text'} for i in range(1, 4)]
    monkeypatch.setattr(families, '_template_llm_complete', lambda *a, **kw: SimpleNamespace(data={
        'families': [{'members': [0, 2], 'reason': '版式一致'}, {'members': [1], 'reason': '需核对'}],
    }))
    result = families.suggest_template_families(slices, cells, owner_id=7, source_body=source())
    assert [item['members'] for item in result] == [[0, 2], [1]]
    assert [item['fragments'][0]['range'] for item in slices] == ['A1:B1', 'A2:B2', 'A3:B3']


@pytest.mark.parametrize('members', [[0, 0], [0], [0, 2], [0, True]])
def test_rejects_duplicate_missing_or_invalid_family_members(monkeypatch, members):
    slices = [{'fragments': [{'sheet': 'S', 'range': f'A{i}:A{i}'}]} for i in range(1, 3)]
    monkeypatch.setattr(families, '_template_llm_complete', lambda *a, **kw: SimpleNamespace(data={
        'families': [{'members': members, 'reason': 'synthetic'}],
    }))
    with pytest.raises(ReviewedExcelError):
        families.suggest_template_families(slices, [], owner_id=7)


def test_rejects_merging_truncated_source_evidence(monkeypatch):
    slices = [{'fragments': [{'sheet': 'S', 'range': 'A1:A121'}]}, {'fragments': [{'sheet': 'S', 'range': 'B1:B1'}]}]
    cells = [{'sheet': 'S', 'cell': f'A{i}', 'value': str(i), 'kind': 'text'} for i in range(1, 122)]
    cells.append({'sheet': 'S', 'cell': 'B1', 'value': 'header', 'kind': 'text'})
    monkeypatch.setattr(families, '_template_llm_complete', lambda *a, **kw: SimpleNamespace(data={
        'families': [{'members': [0, 1], 'reason': 'synthetic'}],
    }))
    with pytest.raises(ReviewedExcelError, match='证据不完整'):
        families.suggest_template_families(slices, cells, owner_id=7, source_body=source())


def test_slice_metadata_cache_is_scoped_and_does_not_store_workbook():
    from app.fastapi_routes import reviewed_excel_template as route

    key = (11, 7, 'classification', 'version', 'source-hash')
    other_owner = (11, 8, 'classification', 'version', 'source-hash')
    route._remember_slice_metadata(key, [{'fragments': [{'sheet': 'S', 'range': 'A1:A1'}], 'workbook': b'private'}])
    try:
        assert route._cached_slice_metadata(key) == [{'fragments': [{'sheet': 'S', 'range': 'A1:A1'}], 'type_label': ''}]
        assert route._cached_slice_metadata(other_owner) is None
    finally:
        with route._SLICE_METADATA_LOCK:
            route._SLICE_METADATA.pop(key, None)


def test_model_prompts_do_not_force_ledger_rows_into_separate_documents():
    from app.application.reviewed_excel_reference_prompts import IDENTIFY_PROMPT, RANGE_GROUP_PROMPT

    assert 'do not split individual rows' in IDENTIFY_PROMPT
    assert 'Different dates or order keys can be rows of the same continuous ledger' in RANGE_GROUP_PROMPT
    assert 'keep those as separate documents' not in RANGE_GROUP_PROMPT


def test_dispatch_markers_distinguish_local_failure_from_answered_rejection(monkeypatch):
    events = []
    with pytest.raises(ReviewedExcelError, match='文档过多'):
        families.suggest_template_families([{}] * 101, [], owner_id=7,
                                           on_dispatch=lambda: events.append('sent'),
                                           on_answer=lambda: events.append('answered'))
    assert events == []
    monkeypatch.setattr(families, '_template_llm_complete', lambda *a, **kw: SimpleNamespace(data={'families': []}))
    with pytest.raises(ReviewedExcelError, match='遗漏或重复'):
        families.suggest_template_families([{'fragments': []}], [], owner_id=7,
                                           on_dispatch=lambda: events.append('sent'),
                                           on_answer=lambda: events.append('answered'))
    assert events == ['sent', 'answered']


def test_formula_heavy_candidate_still_sends_business_values_to_model(monkeypatch):
    from app.application import reviewed_excel_template as template
    from app.application.elt.llm_assist import LlmAssistResult

    book = Workbook()
    sheet = book.active
    sheet['A1'] = '产品名称'
    sheet['A2'] = '实际商品'
    for row in range(1, 150):
        sheet.cell(row, 2, '=1+1')
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    review = template.inspect_workbook(buffer.getvalue())
    captured = []

    def answer(messages, *args, **kwargs):
        import json
        captured.append(json.loads(messages[-1]['content']))
        return LlmAssistResult(used_llm=True, data={'candidates': [
            {'clear': [{'sheet': sheet.title, 'cell': 'A2'}], 'reason': '清除业务值'}
            for _ in range(3)
        ]})

    monkeypatch.setattr(template, '_template_llm_complete', answer)
    template.refine_proposal(review, template.make_proposals(review)['version'], '生成候选', owner_id=7, initial=True)
    assert any(cell['cell'] == 'A2' for cell in captured[0]['cells'])
    assert all(cell['kind'] != 'formula' for cell in captured[0]['cells'])


def test_independent_model_audit_repairs_omitted_business_cells(monkeypatch):
    from app.application import reviewed_excel_template as template
    from app.application.elt.llm_assist import LlmAssistResult
    from app.application.reviewed_excel_audit import call_key, current_call_id

    book = Workbook()
    sheet = book.active
    sheet['A1'] = '产品名称'
    sheet['A2'] = '遗漏商品'
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    review = template.inspect_workbook(buffer.getvalue())
    keys = []

    def answer(messages, *args, **kwargs):
        keys.append(current_call_id())
        if messages[0]['content'].startswith('Independently audit'):
            return LlmAssistResult(used_llm=True, data={'clear': [{'sheet': sheet.title, 'cell': 'A2'}], 'reason': '业务值'})
        return LlmAssistResult(used_llm=True, data={'candidates': [{'clear': [], 'reason': 'synthetic'} for _ in range(3)]})

    monkeypatch.setattr(template, '_template_llm_complete', answer)
    with call_key('review'):
        result = template.refine_proposal(review, template.make_proposals(review)['version'], '生成候选', owner_id=7, initial=True)
    assert all(candidate['clear'] == [{'sheet': sheet.title, 'cell': 'A2'}] for candidate in result['candidates'])
    assert keys == ['review-a1', 'review-verify1']
    assert result['model']['audit_summary']['sent_cells']


def test_audit_disconnect_keeps_primary_candidate_and_marks_it_for_review(monkeypatch):
    import httpx

    from app.application import reviewed_excel_template as template
    from app.application.elt.llm_assist import LlmAssistResult

    book = Workbook()
    book.active['A1'] = '产品名称'
    book.active['A2'] = '业务值'
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    review = template.inspect_workbook(buffer.getvalue())
    calls = []

    def answer(messages, *args, **kwargs):
        calls.append(messages[0]['content'])
        if messages[0]['content'].startswith('Independently audit'):
            raise httpx.ReadTimeout('unknown response')
        return LlmAssistResult(used_llm=True, data={'candidates': [{'clear': [], 'reason': 'synthetic'} for _ in range(3)]})

    monkeypatch.setattr(template, '_template_llm_complete', answer)
    result = template.refine_proposal(review, template.make_proposals(review)['version'], '生成候选', owner_id=7, initial=True)
    assert result['model']['audit_degraded'] is True
    assert len(result['candidates']) == 3 and len(calls) == 2


def test_large_template_covers_all_values_in_separate_model_batches(monkeypatch):
    import json
    import threading
    import time

    from app.application import reviewed_excel_template as template
    from app.application.elt.llm_assist import LlmAssistResult
    from app.application.reviewed_excel_audit import call_key, current_call_id

    book = Workbook()
    sheet = book.active
    sheet['A1'] = '产品名称'
    for row in range(2, 183):
        sheet.cell(row, 1, f'合成商品{row}')
        sheet.cell(row, 2, '=1+1')
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    review = template.inspect_workbook(buffer.getvalue())
    calls = []
    lock = threading.Lock()
    active, peak = 0, 0

    def answer(messages, *args, **kwargs):
        nonlocal active, peak
        payload = json.loads(messages[-1]['content'])
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append((current_call_id(), payload['cells']))
        time.sleep(0.03)
        with lock:
            active -= 1
        clear = [{'sheet': c['sheet'], 'cell': c['cell']} for c in payload['cells'] if c['cell'] != 'A1']
        if messages[0]['content'].startswith('Independently audit'):
            return LlmAssistResult(used_llm=True, data={'clear': clear, 'reason': '复核'})
        return LlmAssistResult(used_llm=True, data={'candidates': [{'clear': clear, 'reason': '清除业务值'} for _ in range(3)]})

    monkeypatch.setattr(template, '_template_llm_complete', answer)
    with call_key('test-call'):
        result = template.refine_proposal(review, template.make_proposals(review)['version'], '生成候选', owner_id=7, initial=True)
    assert len(calls) == 4 and len({call[0] for call in calls}) == 4
    assert peak == 2
    assert all(len(cells) <= 150 for _, cells in calls)
    assert {item['cell'] for item in result['candidates'][0]['clear']} == {f'A{row}' for row in range(2, 183)}
    assert result['model']['truncated'] is False


def test_unsent_batch_resumes_without_repeating_completed_model_calls(monkeypatch):
    import json
    import threading

    from app.application import reviewed_excel_template as template
    from app.application.elt.llm_assist import LlmAssistResult
    from app.application.reviewed_excel_audit import ModelRequestNotSent, call_key, current_call_id

    book = Workbook()
    for row in range(1, 182):
        book.active.cell(row, 1, f'合成商品{row}')
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    review = template.inspect_workbook(buffer.getvalue())
    checkpoint = {}
    completed = threading.Event()
    keys = []
    failing = True

    def save_batch(index, digest, status, result):
        checkpoint[str(index)] = {'digest': digest, 'status': status, **({'result': result} if result else {})}
        if index == 0 and status == 'complete':
            completed.set()

    def answer(messages, *args, **kwargs):
        cells = json.loads(messages[-1]['content'])['cells']
        key = current_call_id()
        keys.append(key)
        if '-b2-' in key and failing:
            assert completed.wait(timeout=3)
            raise ModelRequestNotSent('连接未建立')
        clear = [{'sheet': cell['sheet'], 'cell': cell['cell']} for cell in cells]
        return LlmAssistResult(used_llm=True, data={'candidates': [{'clear': clear, 'reason': '实例'} for _ in range(3)]})

    monkeypatch.setattr(template, '_template_llm_complete', answer)
    parent = template.make_proposals(review)['version']
    with call_key('request'), pytest.raises(ModelRequestNotSent):
        template.refine_proposal(review, parent, '生成候选', owner_id=7, initial=True, batch_checkpoint=save_batch)
    assert checkpoint['0']['status'] == 'complete' and checkpoint['1']['status'] == 'not_sent'
    failing = False
    keys.clear()
    with call_key('request'):
        result = template.refine_proposal(review, parent, '生成候选', owner_id=7, initial=True, cached_batches=checkpoint, batch_checkpoint=save_batch, batch_attempt=2)
    assert len(keys) == 1 and '-r2-b2-' in keys[0]
    assert len(result['candidates'][0]['clear']) == 181


def test_late_candidate_read_is_scoped_and_never_calls_model(monkeypatch):
    import json
    from contextlib import nullcontext

    from app.fastapi_routes import reviewed_excel_template as routes

    state = {'versions': [{'version': 'v1'}], 'template_candidate_requests': {
        'k': {'state': 'completed', 'review_id': 'review-1'},
    }}
    summary = {'selected_region': {'classification_id': 'classification', 'version': 'v1', 'auto_slice_index': 2}}
    monkeypatch.setattr(routes, '_identity', lambda user: (1, 7))
    monkeypatch.setattr(routes, 'get_db', lambda: nullcontext(object()))
    monkeypatch.setattr(routes, '_classification_run', lambda db, cid, tenant, owner: SimpleNamespace(draft_json=json.dumps(state)))
    monkeypatch.setattr(routes, '_run', lambda db, rid, tenant, owner: SimpleNamespace(id=rid, summary_json=json.dumps(summary)))
    monkeypatch.setattr(routes, '_stored_candidate_response', lambda db, rid, tenant, owner: {'review_id': rid})
    assert routes.reviewed_excel_candidate_result('classification', 'v1', 2, user={}) == {'status': 'complete', 'review': {'review_id': 'review-1'}}
    assert routes.reviewed_excel_candidate_result('classification', 'v1', 1, user={}) == {'status': 'pending'}
    from app.application import reviewed_excel_audit
    state['template_candidate_requests'] = {'active': {'state': 'sent', 'version': 'v1', 'slice_index': 2}}
    monkeypatch.setattr(reviewed_excel_audit, 'is_live', lambda key: True)
    assert routes.reviewed_excel_candidate_result('classification', 'v1', 2, user={}) == {'status': 'pending'}
    monkeypatch.setattr(reviewed_excel_audit, 'is_live', lambda key: False)
    assert routes.reviewed_excel_candidate_result('classification', 'v1', 2, user={}) == {'status': 'unknown'}


def test_family_result_preserves_concurrent_candidate_claim(monkeypatch):
    import json
    from contextlib import nullcontext

    from app.fastapi_routes import reviewed_excel_template as routes

    stored = {'draft': json.dumps({'versions': [{'version': 'v1'}]})}
    db = SimpleNamespace(expire_all=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(routes, '_identity', lambda user: (1, 7))
    monkeypatch.setattr(routes, 'require_model_session', lambda *args: object())
    monkeypatch.setattr(routes, 'get_db', lambda: nullcontext(db))
    monkeypatch.setattr(routes, '_classification_run', lambda *args: SimpleNamespace(draft_json=stored['draft'], file_sha256='sha'))
    monkeypatch.setattr(routes, '_cached_slice_metadata', lambda *args: [{'fragments': []}])
    monkeypatch.setattr(routes, '_source', lambda *args: b'synthetic')
    monkeypatch.setattr(routes, 'inspect_workbook', lambda *args: {'cells': []})
    monkeypatch.setattr(routes, 'bind_model_session', lambda *args: nullcontext())
    monkeypatch.setattr(routes, '_recheck', lambda *args: None)

    def cas(db, run, old, state):
        assert old == stored['draft']
        stored['draft'] = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def suggest(*args, on_dispatch, on_answer, **kwargs):
        on_dispatch()
        state = json.loads(stored['draft'])
        state['template_candidate_requests'] = {'other': {'state': 'sent'}}
        stored['draft'] = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        on_answer()
        return [{'members': [0], 'reason': 'synthetic'}]

    monkeypatch.setattr(routes, '_classification_cas', cas)
    monkeypatch.setattr(families, 'suggest_template_families', suggest)
    response = routes.reviewed_excel_template_families('classification', 'v1', object(), user={})
    final = json.loads(stored['draft'])
    assert response['status'] == final['template_families']['status'] == 'complete'
    assert final['template_candidate_requests']['other']['state'] == 'sent'
