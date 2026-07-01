from __future__ import annotations

import json

import pytest

import modstore_server.models as models


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "ownership.sqlite"))
    models.init_db()
    yield
    models._engine = None
    models._SessionFactory = None


def test_code_ownership_resolves_scope_and_forbidden(monkeypatch):
    from modstore_server import code_ownership

    code_ownership.load_code_ownership_table.cache_clear()
    monkeypatch.setattr(
        code_ownership,
        "load_code_ownership_table",
        lambda: [
            {
                "id": "modstore-backend-api",
                "area": "modstore-backend",
                "scope_globs": ["MODstore_deploy/modstore_server/**"],
                "forbidden_globs": ["MODstore_deploy/modstore_server/payment_*.py"],
            },
            {
                "id": "payment-billing-reconciler",
                "area": "modstore-backend",
                "scope_globs": ["MODstore_deploy/modstore_server/payment_*.py"],
                "forbidden_globs": [],
            },
        ],
    )

    api = code_ownership.resolve_code_owners(
        ["/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore_server/workbench_api.py"]
    )
    assert api["owner_ids"][0] == "modstore-backend-api"

    payment = code_ownership.resolve_code_owners(
        ["成都修茈科技有限公司/MODstore_deploy/modstore_server/payment_routes.py"]
    )
    assert payment["owner_ids"][0] == "payment-billing-reconciler"
    assert "modstore-backend-api" not in payment["owner_ids"]


def test_code_ownership_double_star_slash_matches_one_level(monkeypatch):
    from modstore_server import code_ownership

    code_ownership.load_code_ownership_table.cache_clear()
    monkeypatch.setattr(
        code_ownership,
        "load_code_ownership_table",
        lambda: [
            {
                "id": "site-content-editor",
                "area": "site-and-marketing",
                "scope_globs": ["corp-butler/**/*.js"],
                "forbidden_globs": [],
            }
        ],
    )

    out = code_ownership.resolve_code_owners(["corp-butler/corp-butler.js"])

    assert out["owner_ids"] == ["site-content-editor"]


def test_code_ownership_merges_stale_routing_table_with_yuangon(monkeypatch):
    from modstore_server import code_ownership

    code_ownership.load_code_ownership_table.cache_clear()
    monkeypatch.setattr(
        code_ownership,
        "_load_from_routing_table",
        lambda: [
            {
                "id": "daily-orchestrator",
                "scope_globs": ["MODstore_deploy/**"],
                "forbidden_globs": [],
            }
        ],
    )
    monkeypatch.setattr(
        code_ownership,
        "_load_from_yuangon",
        lambda: [
            {
                "id": "fhd-core-maintainer",
                "scope_globs": ["FHD/app/**"],
                "forbidden_globs": [],
            }
        ],
    )

    rows = code_ownership.load_code_ownership_table()
    ids = {row["id"] for row in rows}

    assert {"daily-orchestrator", "fhd-core-maintainer"} <= ids


def test_market_ranks_code_owner_from_incident_files(fresh_db, monkeypatch):
    from modstore_server import code_ownership
    from modstore_server.employee_task_market import rank_market_candidates

    code_ownership.load_code_ownership_table.cache_clear()
    monkeypatch.setattr(
        "modstore_server.employee_task_market.resolve_incident_ownership",
        lambda payload, source="", event_type="", limit=8: {
            "files": ["MODstore_deploy/modstore_server/workbench_api.py"],
            "matched": True,
            "owner_ids": ["modstore-backend-api"],
            "owners": [
                {
                    "area": "modstore-backend",
                    "employee_id": "modstore-backend-api",
                    "match_count": 1,
                    "match_score": 80,
                    "matched_files": ["MODstore_deploy/modstore_server/workbench_api.py"],
                    "matched_globs": ["MODstore_deploy/modstore_server/workbench_api.py"],
                }
            ],
        },
    )

    sf = models.get_session_factory()
    with sf() as session:
        session.add(
            models.IncidentEvent(
                event_type="on_error",
                source="pytest",
                payload_json=json.dumps(
                    {
                        "summary": "workbench_api.py 500",
                        "files": ["MODstore_deploy/modstore_server/workbench_api.py"],
                    },
                    ensure_ascii=False,
                ),
                fingerprint="owner-test",
            )
        )
        session.commit()
        event_id = int(session.query(models.IncidentEvent.id).scalar())

    out = rank_market_candidates(event_id)
    assert out["ok"] is True
    assert out["code_ownership"]["owner_ids"] == ["modstore-backend-api"]
    assert out["candidates"][0]["employee_id"] == "modstore-backend-api"
    assert out["candidates"][0]["ownership_bonus"] > 0


def test_market_owner_task_context_names_owned_files():
    from modstore_server.employee_task_market import _ownership_task_context

    text = _ownership_task_context(
        {
            "matched_files": ["MODstore_deploy/modstore_server/workbench_api.py"],
            "matched_globs": ["MODstore_deploy/modstore_server/**"],
        }
    )

    assert "代码负责人" in text
    assert "MODstore_deploy/modstore_server/workbench_api.py" in text
    assert "可执行修复" in text


def test_market_keeps_code_owner_even_when_catalog_is_missing(fresh_db, monkeypatch):
    from modstore_server.employee_task_market import rank_market_candidates

    monkeypatch.setattr(
        "modstore_server.employee_task_market.resolve_incident_ownership",
        lambda payload, source="", event_type="", limit=8: {
            "files": ["MODstore_deploy/modstore_server/workbench_api.py"],
            "matched": True,
            "owner_ids": ["modstore-backend-api"],
            "owners": [
                {
                    "area": "modstore-backend",
                    "employee_id": "modstore-backend-api",
                    "match_count": 1,
                    "match_score": 80,
                    "matched_files": ["MODstore_deploy/modstore_server/workbench_api.py"],
                    "matched_globs": ["MODstore_deploy/modstore_server/workbench_api.py"],
                }
            ],
        },
    )

    sf = models.get_session_factory()
    with sf() as session:
        session.add(
            models.CatalogItem(
                pkg_id="daily-orchestrator",
                version="1.0.0",
                name="Daily",
                artifact="employee_pack",
            )
        )
        session.add(
            models.EmployeeTriggerBinding(
                employee_id="daily-orchestrator",
                event_type="on_error",
                is_active=True,
                priority=1,
            )
        )
        session.add(
            models.IncidentEvent(
                event_type="on_error",
                source="pytest",
                payload_json=json.dumps(
                    {"files": ["MODstore_deploy/modstore_server/workbench_api.py"]},
                    ensure_ascii=False,
                ),
                fingerprint="owner-catalog-missing",
            )
        )
        session.commit()
        event_id = int(
            session.query(models.IncidentEvent.id)
            .filter(models.IncidentEvent.fingerprint == "owner-catalog-missing")
            .scalar()
        )

    out = rank_market_candidates(event_id)
    ids = [row["employee_id"] for row in out["candidates"]]
    assert "modstore-backend-api" in ids
    owner = next(row for row in out["candidates"] if row["employee_id"] == "modstore-backend-api")
    assert owner["catalog_available"] is False
    assert owner["ownership_bonus"] > 0


def test_incident_team_reserves_fix_role_for_code_owner(monkeypatch):
    from modstore_server import incident_team_orchestrator as team

    monkeypatch.setattr(
        team,
        "_candidate_rows",
        lambda _event_id: [
            {
                "employee_id": "modstore-backend-api",
                "score": 100,
                "code_ownership": {"match_count": 1},
            },
            {"employee_id": "test-qa-runner", "score": 80, "code_ownership": {}},
            {"employee_id": "change-request-auditor", "score": 70, "code_ownership": {}},
        ],
    )

    out = team.build_incident_team(123)
    roles = {row["role"]: row["employee_id"] for row in out["team"]}
    assert out["code_owner"] == "modstore-backend-api"
    assert out["code_owner_match"]["match_count"] == 1
    assert roles["fix"] == "modstore-backend-api"


def test_incident_team_fix_task_includes_code_owner_context():
    from modstore_server.incident_team_orchestrator import _task_for_role

    task = _task_for_role(
        code_ownership={
            "matched_files": ["MODstore_deploy/modstore_server/workbench_api.py"],
            "matched_globs": ["MODstore_deploy/modstore_server/**"],
        },
        event_type="on_error",
        payload={"summary": "workbench_api.py 500"},
        role="fix",
        scout_result={"ok": True},
    )

    assert "代码负责人" in task
    assert "MODstore_deploy/modstore_server/workbench_api.py" in task
    assert "可执行处理" in task
