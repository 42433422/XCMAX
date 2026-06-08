from modstore_server.employee_ai_scaffold import _default_capabilities
from modstore_server.employee_scaffold_presets import list_preset_keys, resolve_preset_capabilities


def test_resolve_preset_engineering():
    caps, meta = resolve_preset_capabilities("engineering")
    assert "code.review" in caps
    assert meta.get("preset_key") == "engineering"


def test_list_preset_keys_sorted():
    keys = list_preset_keys()
    assert keys == sorted(keys)
    assert "design" in keys


def test_default_capabilities_department_preset():
    caps = _default_capabilities(
        pid="x",
        name="y",
        description="z",
        employee_id="e",
        label="l",
        capabilities=[],
        department_preset="qa",
    )
    assert "test.plan_draft" in caps
