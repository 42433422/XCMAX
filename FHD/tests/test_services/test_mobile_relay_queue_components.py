"""Relay completion stays within the authenticated desktop's persisted task ownership."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services import mobile_relay_service as relay


@pytest.fixture
def relay_queue(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'synthetic-relay.db'}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def database():
        with sessions.begin() as db:
            yield db

    monkeypatch.setattr(relay, "get_db", database)
    notifications = Mock()
    service = relay.MobileRelayService()
    monkeypatch.setattr(service, "_notify_task_creator", notifications)
    try:
        yield SimpleNamespace(service=service, database=database, notifications=notifications)
    finally:
        engine.dispose()


def _paired(context, user_id, label):
    desktop = context.service.register_desktop(label=label, device_id=label)
    paired = context.service.bind_mobile_by_account(
        user_id=user_id, username=label, pairing_code=desktop["pairing_code"]
    )
    assert paired is not None
    return desktop


@pytest.mark.parametrize("second_user", [7401, 7402])
def test_completion_cannot_read_or_notify_another_desktop(relay_queue, second_user):
    own = _paired(relay_queue, 7401, "Synthetic device A")
    other = _paired(relay_queue, second_user, "Synthetic device B")
    service = relay_queue.service
    task = service.create_task(
        user_id=second_user,
        relay_id=other["relay_id"],
        kind="synthetic.invoke",
        payload={"owner": "synthetic-b"},
    )

    response = service.complete_desktop_task(
        relay_id=own["relay_id"],
        desktop_token=own["desktop_token"],
        task_id=task["task_id"],
        status="completed",
        result={"source": "synthetic-a"},
    )

    assert service.get_task(user_id=second_user, task_id=task["task_id"]) == task
    assert response is None
    relay_queue.notifications.assert_not_called()


def test_completion_does_not_publish_a_task_when_the_update_was_not_applied(relay_queue):
    desktop = _paired(relay_queue, 7403, "Synthetic device")
    service = relay_queue.service
    task = service.create_task(user_id=7403, relay_id=desktop["relay_id"], kind="synthetic.invoke")
    with relay_queue.database() as db:
        # A real zero-row update models the optimistic-write failure boundary.
        db.execute(
            text(
                "CREATE TRIGGER synthetic_reject_completion BEFORE UPDATE OF status "
                "ON mobile_relay_tasks WHEN NEW.status = 'completed' "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
        )

    response = service.complete_desktop_task(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        task_id=task["task_id"],
        status="completed",
    )

    assert service.get_task(user_id=7403, task_id=task["task_id"]) == task
    assert response is None
    relay_queue.notifications.assert_not_called()


def test_http_completion_rejects_a_task_owned_by_another_desktop(relay_queue, monkeypatch):
    from app.fastapi_routes import mobile_api_extensions as extensions

    own = _paired(relay_queue, 7404, "Synthetic HTTP A")
    other = _paired(relay_queue, 7405, "Synthetic HTTP B")
    task = relay_queue.service.create_task(
        user_id=7405,
        relay_id=other["relay_id"],
        kind="synthetic.invoke",
        payload={"private_marker": "synthetic-device-b-payload"},
    )
    monkeypatch.setattr(extensions, "MobileRelayService", lambda: relay_queue.service)
    app = FastAPI()
    app.include_router(extensions.extension_router, prefix="/api/mobile/v1")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            f"/api/mobile/v1/relay/desktop/tasks/{task['task_id']}/complete",
            json={
                "relay_id": own["relay_id"],
                "desktop_token": own["desktop_token"],
                "status": "completed",
            },
        )

    assert response.status_code == 404, response.text
    assert "synthetic-device-b-payload" not in response.text
    relay_queue.notifications.assert_not_called()


def test_completion_notifies_only_after_the_result_is_committed(relay_queue, monkeypatch):
    desktop = _paired(relay_queue, 7406, "Synthetic committed result")
    service = relay_queue.service
    task = service.create_task(user_id=7406, relay_id=desktop["relay_id"], kind="synthetic.invoke")
    observed = []

    def after_commit(completed):
        # A separate connection must already see the row at the callback boundary.
        with relay_queue.database() as db:
            status = db.execute(
                text("SELECT status FROM mobile_relay_tasks WHERE task_id = :task_id"),
                {"task_id": task["task_id"]},
            ).scalar_one()
        observed.append((completed, status))

    monkeypatch.setattr(service, "_notify_task_creator", after_commit)
    response = service.complete_desktop_task(
        relay_id=desktop["relay_id"],
        desktop_token=desktop["desktop_token"],
        task_id=task["task_id"],
        status="done",
        result={"summary": "Synthetic completion"},
    )

    assert response["status"] == "completed"
    assert response["result"] == {"summary": "Synthetic completion"}
    assert observed == [(response, "completed")]
    assert service.get_task(user_id=7406, task_id=task["task_id"]) == response


def test_failed_transaction_neither_changes_the_task_nor_notifies(relay_queue, monkeypatch):
    desktop = _paired(relay_queue, 7407, "Synthetic failed commit")
    service = relay_queue.service
    task = service.create_task(user_id=7407, relay_id=desktop["relay_id"], kind="synthetic.invoke")

    @contextmanager
    def failed_commit():
        with relay_queue.database() as db:
            yield db
            raise OSError("synthetic transaction failure")

    with monkeypatch.context() as transaction:
        # Resolving the existing DB patch point must remain lazy after construction.
        transaction.setattr(relay, "get_db", failed_commit)
        with pytest.raises(OSError, match="synthetic transaction failure"):
            service.complete_desktop_task(
                relay_id=desktop["relay_id"],
                desktop_token=desktop["desktop_token"],
                task_id=task["task_id"],
                status="completed",
            )

    assert service.get_task(user_id=7407, task_id=task["task_id"]) == task
    relay_queue.notifications.assert_not_called()


def test_pairing_and_queue_work_without_importing_the_service_facade(tmp_path):
    code = dedent(
        """
        import importlib.abc
        import socket
        import sys
        from contextlib import contextmanager
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        forbidden = {
            'app.domain.shared_services.mobile_relay_service',
            'app.application.facades.mobile_relay_facade',
        }
        class NoFacade(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in forbidden:
                    raise AssertionError('component imported its service facade')
        sys.meta_path.insert(0, NoFacade())
        def no_network(*args, **kwargs):
            raise AssertionError('independent relay components attempted network IO')
        socket.socket.connect = no_network

        from app.domain.shared_services.mobile_relay_pairing import RelayPairing
        from app.domain.shared_services.mobile_relay_tasks import RelayTaskQueue
        from app.application.mobile_relay_ports import PairingPorts, TaskPorts
        from app.infrastructure.mobile_relay import repository

        engine = create_engine('sqlite:///' + sys.argv[1])
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        @contextmanager
        def database():
            with sessions.begin() as db:
                yield db
        pairing = RelayPairing(PairingPorts(
            database=database,
            ensure_tables=repository.ensure_tables,
            fresh_pairing_code=repository.fresh_pairing_code,
            desktop_for_token=repository.desktop_for_token,
            public_desktop=repository.public_desktop,
        ))
        notifications = []
        tasks = RelayTaskQueue(TaskPorts(
            database=database,
            ensure_tables=repository.ensure_tables,
            desktop_belongs_to_user=lambda user_id, relay_id:
                repository.desktop_belongs_to_user(
                    user_id=user_id, relay_id=relay_id,
                    database=database, ensure_schema=repository.ensure_tables,
                ),
            desktop_for_token=repository.desktop_for_token,
            public_desktop=repository.public_desktop,
            notify_task_creator=notifications.append,
            get_task=lambda user_id, task_id: tasks.get_task(user_id=user_id, task_id=task_id),
        ))
        desktop = pairing.register_desktop(label='Synthetic isolated', device_id='isolated')
        assert pairing.bind_mobile_by_account(
            user_id=7408, username='Synthetic owner', pairing_code=desktop['pairing_code']
        ) is not None
        task = tasks.create_task(user_id=7408, relay_id=desktop['relay_id'], kind='synthetic.invoke')
        result = tasks.complete_desktop_task(
            relay_id=desktop['relay_id'], desktop_token=desktop['desktop_token'],
            task_id=task['task_id'], status='completed', result={'ok': True},
        )
        assert result['status'] == 'completed'
        assert result['result'] == {'ok': True}
        assert notifications == [result]
        assert forbidden.isdisjoint(sys.modules)
        engine.dispose()
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "independent-relay.db")],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
