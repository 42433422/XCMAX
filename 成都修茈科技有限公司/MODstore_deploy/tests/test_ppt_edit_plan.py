from __future__ import annotations

from modstore_server.ppt_edit_plan import (
    parse_edit_plan_json,
    plan_from_presentation,
    validate_edit_plan,
    validate_ooxml_fragment,
)


def test_validate_edit_plan_compose():
    raw = {
        "mode": "compose",
        "title": "产品介绍",
        "slides": [{"index": 1, "title": "概述", "bullets": ["A", "B"]}],
        "ops": [{"op": "set_slide_text", "slide": 1, "title": "概述", "bullets": ["A"]}],
    }
    plan, errs = validate_edit_plan(raw)
    assert not errs
    assert plan["mode"] == "compose"
    assert len(plan["slides"]) == 1


def test_reject_bad_ooxml():
    err = validate_ooxml_fragment("<script>alert(1)</script>")
    assert err is not None


def test_plan_from_presentation():
    table = {
        "title": "Deck",
        "slides": [{"index": 1, "title": "S1", "bullets": ["x"], "images": []}],
    }
    plan = plan_from_presentation(table, mode="enhance")
    assert plan["mode"] == "enhance"
    assert any(o.get("op") == "set_slide_text" for o in plan["ops"])


def test_parse_edit_plan_json_wrapper():
    text = '{"ppt_edit_plan": {"mode": "compose", "title": "T", "slides": [], "ops": []}}'
    plan, errs = parse_edit_plan_json(text)
    assert not errs
    assert plan["title"] == "T"
