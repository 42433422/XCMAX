"""Exercise an explicitly approved action, then read its original HTTP receipt.

Admission tests use the ordinary TestClient. These business/readback tests need
the effect after a real bound grant, not the retired route_confirmed shortcut.
"""

from __future__ import annotations

from uuid import uuid4


class ApprovedCapabilityClient:
    def __init__(self, client, repository, actor):
        self.client = client
        self.repository = repository
        self.actor = actor
        self.client.headers.update(actor.headers)

    def __getattr__(self, name):
        return getattr(self.client, name)

    def request(self, method, url, **kwargs):
        from app.application.agent_orchestrator import AgentOrchestrator
        from tests.test_application.test_agent_user_decision_pause import (
            _approve_and_execute,
        )

        headers = dict(kwargs.pop("headers", {}) or {})
        if not any(key.lower() == "idempotency-key" for key in headers):
            headers["Idempotency-Key"] = uuid4().hex
        response = self.client.request(method, url, headers=headers, **kwargs)
        receipt = response.json()
        if not receipt.get("pending_approval"):
            return response
        assert response.status_code == 202, response.text
        original = self.repository.get(receipt["run_id"])
        assert original is not None and original.status == "waiting_user"
        assert original.user_id == str(self.actor.user_id)
        assert not original.tool_calls
        completed = _approve_and_execute(
            AgentOrchestrator(repository=self.repository), original, self.actor
        )
        assert completed.run_id == original.run_id
        response = self.client.request(method, url, headers=headers, **kwargs)
        assert response.json()["run_id"] == original.run_id
        assert response.json().get("pending_approval") is not True
        return response

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)
