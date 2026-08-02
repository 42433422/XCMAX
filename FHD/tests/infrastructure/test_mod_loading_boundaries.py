from types import SimpleNamespace


def test_entitled_but_uninstalled_mod_does_not_enter_load_or_failure_loop(monkeypatch) -> None:
    from app import runtime_integrity
    from app.infrastructure.mods import missing_local_state
    from app.infrastructure.mods import mod_manager as module

    load_calls: list[str] = []
    issues: list[tuple[str, str, float]] = []
    manager = SimpleNamespace(
        _loaded_mods=[],
        resolve_mod_directory=lambda _mod_id: None,
        load_mod=lambda mod_id: load_calls.append(mod_id) or False,
    )
    monkeypatch.setattr(module, "is_mods_disabled", lambda: False)
    monkeypatch.setattr(module, "_restore_entitlements_from_session_id", lambda _sid: None)
    monkeypatch.setattr(module, "_mod_allowed_for_api_load", lambda _mid, _sid=None: True)
    monkeypatch.setattr(module, "get_mod_manager", lambda: manager)
    monkeypatch.setattr(
        runtime_integrity,
        "record_runtime_issue",
        lambda issue_id, message, ttl_seconds: issues.append((issue_id, message, ttl_seconds)),
    )
    missing_local_state.clear_mod_missing_locally("artifact-generator")

    assert module.ensure_mod_api_ready("artifact-generator") is False
    assert module.ensure_mod_api_ready("artifact-generator") is False
    assert load_calls == []
    assert issues == [
        (
            "industry_mod:artifact-generator",
            "Industry MOD is entitled but not installed locally: artifact-generator",
            24 * 60 * 60,
        )
    ]
    missing_local_state.clear_mod_missing_locally("artifact-generator")


def test_desktop_sku_never_registers_admin_employee_pack_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    from app.infrastructure.mods import mod_manager as module
    from app.mod_sdk import product_skus

    employee_root = tmp_path / "_employees" / "top-architect"
    employee_root.mkdir(parents=True)
    (employee_root / "manifest.json").write_text(
        '{"id":"top-architect","artifact":"employee_pack","backend":{"entry":"employees/top_architect"}}',
        encoding="utf-8",
    )
    calls: list[str] = []
    monkeypatch.setattr(product_skus, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(
        module,
        "register_employee_pack_routes",
        lambda _app, _manager, pack_id, **_kwargs: calls.append(pack_id) or True,
    )
    manager = SimpleNamespace(mods_root=str(tmp_path))

    module.load_employee_pack_routes(object(), manager)
    assert calls == []
