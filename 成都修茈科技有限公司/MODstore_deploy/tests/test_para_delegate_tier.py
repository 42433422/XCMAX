"""Tier-aware device dispatch for the loops Para bridge.

一级=本机单设备, 二级=多设备协同; 默认一级优先, 按需升二级。与 FHD
super_employee_service 的分级模型同构, 但在 MODstore_deploy 包内独立实现
(两包隔离, 无法跨 import)。
"""

from modstore_server import para_delegate_handler as h


# ─────────────── _resolve_tier ───────────────


def test_default_is_tier_one():
    assert h._resolve_tier({"task": "修复登录"}) == 1


def test_max_devices_gt_one_escalates():
    assert h._resolve_tier({"raw_input": {"max_devices": 3}}) == 2


def test_explicit_tier_hint_two():
    assert h._resolve_tier({"raw_input": {"para_tier": "2"}}) == 2


def test_explicit_tier_hint_one_overrides_text_marker():
    assert h._resolve_tier({"task": "多设备", "raw_input": {"tier": "1"}}) == 1


def test_multi_device_text_marker_escalates():
    assert h._resolve_tier({"task": "调用所有设备跑测试"}) == 2


def test_escalate_flag():
    assert h._resolve_tier({"raw_input": {"escalate": True}}) == 2


def test_multiple_specific_targets_escalates():
    assert h._resolve_tier({"raw_input": {"target_devices": ["d1", "d2"]}}) == 2


def test_single_target_stays_tier_one():
    assert h._resolve_tier({"raw_input": {"target_devices": ["d1"]}}) == 1


def test_all_target_stays_tier_one():
    assert h._resolve_tier({"raw_input": {"target_devices": ["all"]}}) == 1


def test_force_tier_env_one(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "1")
    assert h._resolve_tier({"raw_input": {"max_devices": 5}}) == 1


def test_force_tier_env_two(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_FORCE_TIER", "2")
    assert h._resolve_tier({"task": "闲聊"}) == 2


# ─────────────── _device_eligible ───────────────


def test_eligible_online_with_capability():
    assert h._device_eligible(
        {"id": "d1", "status": "online", "capabilities": {"codex_cli": True}}, "codex"
    )


def test_ineligible_offline():
    assert not h._device_eligible({"id": "d1", "status": "offline"}, "codex")


def test_ineligible_tool_not_installed():
    item = {
        "id": "d1",
        "status": "online",
        "tools": [{"toolName": "codex", "status": "not_installed"}],
    }
    assert not h._device_eligible(item, "codex")


def test_ineligible_tool_running_with_task():
    item = {
        "id": "d1",
        "status": "online",
        "tools": [{"toolName": "codex", "status": "running", "currentTask": "t1"}],
    }
    assert not h._device_eligible(item, "codex")


def test_eligible_by_dev_tool_when_no_tools_list():
    assert h._device_eligible({"id": "d1", "status": "online", "devTool": "codex"}, "codex")


def test_ineligible_non_dict():
    assert not h._device_eligible("nope", "codex")


# ─────────────── _select_local_device ───────────────


def _online_codex(device_id, **extra):
    base = {"id": device_id, "status": "online", "capabilities": {"codex_cli": True}}
    base.update(extra)
    return base


def test_local_prefers_primary():
    devices = [_online_codex("w1"), _online_codex("p1", isPrimary=True)]
    assert [d["id"] for d in h._select_local_device(devices, "codex")] == ["p1"]


def test_local_prefers_configured_device_id(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "w1")
    devices = [_online_codex("w1"), _online_codex("p1", isPrimary=True)]
    assert [d["id"] for d in h._select_local_device(devices, "codex")] == ["w1"]


def test_local_configured_id_not_eligible_returns_empty(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_ID", "p1")
    devices = [
        {"id": "p1", "status": "offline"},
        _online_codex("w1"),
    ]
    assert h._select_local_device(devices, "codex") == []


def test_local_falls_back_to_first_eligible():
    assert [d["id"] for d in h._select_local_device([_online_codex("a")], "codex")] == ["a"]


def test_local_empty_when_none_eligible():
    assert h._select_local_device([{"id": "a", "status": "offline"}], "codex") == []


# ─────────────── _select_fleet_devices ───────────────


def test_fleet_prefers_non_primary_workers():
    devices = [_online_codex("p1", isPrimary=True), _online_codex("w1"), _online_codex("w2")]
    out = h._select_fleet_devices(devices, {"raw_input": {"max_devices": 3}}, "codex")
    assert {d["id"] for d in out} == {"w1", "w2"}


def test_fleet_caps_at_max_devices():
    devices = [_online_codex(f"w{i}") for i in range(6)]
    out = h._select_fleet_devices(devices, {"raw_input": {"max_devices": 2}}, "codex")
    assert len(out) == 2


# ─────────────── _resolve_dispatch_devices ───────────────


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.content = b"x"

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, devices):
        self._devices = devices

    def get(self, url, headers=None):
        return _FakeResp({"devices": self._devices})


def test_explicit_device_id_zero_regression():
    # 显式 device_id → 一级单设备, 不发现
    req = {"device_id": "fixed-dev"}
    tier, devices, reason = h._resolve_dispatch_devices(_FakeClient([]), "http://p", "tok", req)
    assert tier == 1
    assert [d["id"] for d in devices] == ["fixed-dev"]


def test_discovery_tier_one_picks_local(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
    fleet = [_online_codex("p1", isPrimary=True), _online_codex("w1")]
    req = {"task": "修复", "raw_input": {}}
    tier, devices, reason = h._resolve_dispatch_devices(_FakeClient(fleet), "http://p", "tok", req)
    assert tier == 1
    assert [d["id"] for d in devices] == ["p1"]


def test_discovery_escalates_when_primary_lacks_tool(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
    # 主设备装 codex 没装 claude; claude 任务一级选不到 → 升二级到 w1
    fleet = [
        {
            "id": "p1",
            "status": "online",
            "isPrimary": True,
            "tools": [{"toolName": "claude", "status": "not_installed"}],
        },
        {"id": "w1", "status": "online", "tools": [{"toolName": "claude", "status": "idle"}]},
    ]
    monkeypatch.setenv("MODSTORE_PARA_DEV_TOOL", "claude")
    req = {"task": "修复", "raw_input": {}}
    tier, devices, reason = h._resolve_dispatch_devices(_FakeClient(fleet), "http://p", "tok", req)
    assert tier == 2
    assert [d["id"] for d in devices] == ["w1"]


def test_discovery_no_devices_returns_reason(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
    req = {"task": "修复", "raw_input": {}}
    tier, devices, reason = h._resolve_dispatch_devices(_FakeClient([]), "http://p", "tok", req)
    assert devices == []
    assert "未发现在线可用" in reason


def test_discovery_disabled_returns_empty(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)
    monkeypatch.setenv("MODSTORE_PARA_DEVICE_DISCOVERY", "0")
    req = {"task": "修复", "raw_input": {}}
    tier, devices, reason = h._resolve_dispatch_devices(
        _FakeClient([_online_codex("p1")]), "http://p", "tok", req
    )
    assert devices == []
    assert "设备发现关闭" in reason


# ─────────────── _post_para_api 全链路(发现→派发→轮询) ───────────────


class _IntegResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x"
        self.text = ""

    def json(self):
        return self._payload


class _IntegClient:
    """模拟 DevFleet API：/api/devices 列设备, /api/tasks 建任务, /api/tasks/{id} 轮询。"""

    def __init__(self, devices, task_status="completed"):
        self._devices = devices
        self._task_status = task_status
        self.posted_tasks = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        if url.endswith("/api/devices"):
            return _IntegResp({"devices": self._devices})
        if "/api/tasks/" in url:
            return _IntegResp(
                {"task": {"id": "task-1", "status": self._task_status, "subTasks": []}}
            )
        return _IntegResp({}, status_code=404)

    def post(self, url, headers=None, json=None):
        if url.endswith("/api/auth/guest"):
            return _IntegResp({"token": "guest-token"})
        if url.endswith("/api/tasks"):
            self.posted_tasks.append(json)
            return _IntegResp(
                {
                    "task": {"id": "task-1", "status": "running"},
                    "subtask": {"id": f"sub-{len(self.posted_tasks)}", "device_name": "dev"},
                }
            )
        return _IntegResp({}, status_code=404)


def _integ_env(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://para")
    monkeypatch.setenv("MODSTORE_PARA_AUTH_TOKEN", "tok")
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://example.com/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_DISABLE_AUTO_RETRY", "0")  # 跳过 sqlite 写
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_DEVICE_ID", raising=False)


def test_post_para_api_tier_one_discovers_local(monkeypatch):
    _integ_env(monkeypatch)
    client = _IntegClient([_online_codex("p1", isPrimary=True), _online_codex("w1")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **k: client)

    out = h.dispatch_para_delegate(task="修复登录", input_data={}, employee_id="x")

    assert out["ok"] is True
    assert out["para_tier"] == 1
    assert out["device_scope"] == "local_device"
    assert [d["device_id"] for d in out["devices"]] == ["p1"]
    # 一级只派一台
    assert len(client.posted_tasks) == 1
    assert client.posted_tasks[0]["device_id"] == "p1"


def test_post_para_api_tier_two_fans_out(monkeypatch):
    _integ_env(monkeypatch)
    client = _IntegClient([_online_codex("w1"), _online_codex("w2"), _online_codex("w3")])
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **k: client)

    out = h.dispatch_para_delegate(task="跑测试", input_data={"max_devices": 2}, employee_id="x")

    assert out["ok"] is True
    assert out["para_tier"] == 2
    assert out["device_scope"] == "all_devices"
    # 二级扇出到 2 台, 共享同一 task_id
    assert len(client.posted_tasks) == 2
    assert all(p.get("task_id") in (None, "task-1") for p in client.posted_tasks[1:])
    # 第二台 prompt 带"第 2/2 台"分工提示
    assert "第 2/2 台" in client.posted_tasks[1]["prompt"]


def test_post_para_api_no_online_device_outboxes(monkeypatch):
    _integ_env(monkeypatch)
    client = _IntegClient([])  # /api/devices 空
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **k: client)

    out = h.dispatch_para_delegate(task="修复", input_data={}, employee_id="x")

    assert out["ok"] is False
    assert out["status"] == "blocked_no_online_para_device"
    assert client.posted_tasks == []


def test_post_para_api_explicit_device_id_zero_regression(monkeypatch):
    _integ_env(monkeypatch)
    # 显式 device_id → 不发现, 直接派该设备(一级)
    client = _IntegClient([])  # 即便 /api/devices 空也不影响
    monkeypatch.setattr(h.httpx, "Client", lambda *a, **k: client)

    out = h.dispatch_para_delegate(
        task="修复", input_data={"device_id": "fixed-dev"}, employee_id="x"
    )

    assert out["ok"] is True
    assert out["para_tier"] == 1
    assert [d["device_id"] for d in out["devices"]] == ["fixed-dev"]
    assert client.posted_tasks[0]["device_id"] == "fixed-dev"
