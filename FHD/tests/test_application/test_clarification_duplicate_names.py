from app.application.workflow.clarification_lifecycle import resolve_confirmed_target


def test_duplicate_candidate_names_require_explicit_identity():
    candidates = [{"id": 101, "name": "星光"}, {"id": 202, "name": "星光"}]
    assert resolve_confirmed_target("星光", candidates) is None
    assert resolve_confirmed_target("选星光", candidates) is None
    assert resolve_confirmed_target("101", candidates) == {"id": "101"}
    assert resolve_confirmed_target("2", candidates) == {"id": "202"}


def test_overlapping_names_do_not_silently_pick_first():
    candidates = [{"id": 101, "name": "星光贸易"}, {"id": 202, "name": "星光科技"}]
    assert resolve_confirmed_target("星光", candidates) is None
    assert resolve_confirmed_target("星光贸易", candidates) == {"id": "101"}


def test_mentions_and_negations_are_not_candidate_confirmation():
    candidates = [{"id": 101, "name": "星光贸易"}]
    for answer in ("不要星光贸易", "不是星光贸易", "星光", "星光贸易然后删除全部", "星光贸易吗？"):
        assert resolve_confirmed_target(answer, candidates) is None
    assert resolve_confirmed_target("星光贸易", candidates) == {"id": "101"}
