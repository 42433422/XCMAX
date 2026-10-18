"""派给 dot（Para 工具 dolt）的客服工单：控制标记、模式、脱敏；其他工具不变。"""

import re

import pytest

from modstore_server import dot_ticket_dispatch as dot
from modstore_server import para_delegate_handler as mod

MARKER = re.compile(r"^\[xcmax:[0-9a-f]{32}:[0-9a-f]{32}\]")
# dot 转接程序 safeText 的拒收规则（devfleet-private scripts/lib/dot-mailbox.mjs）
DOT_REJECT = re.compile(
    r"(?i)(?:bearer\s+\S+|-----BEGIN .*PRIVATE KEY|(?:password|passwd|api[_-]?key|secret|token)"
    r"\s*[:=]\s*\S+|https?://[^/\s:@]+:[^/\s@]+@)"
)
# dot 侧 classify（devfleet-private scripts/lib/dot-session.mjs）
DOT_ACCOUNT = re.compile(
    r"(账号|帐号|账户|帐户|登录|登陆|密码|验证码|注册|实名|权限|封号|解封|account|login|log in"
    r"|sign[ -]?in|password|credential|2fa|otp)",
    re.I,
)
DOT_REPORT_ONLY = re.compile(
    r"(report_only\s*[:=]\s*(true|1)|MODSTORE_REPORT_ONLY=1|仅出报告|只出报告|只读)", re.I
)

TICKET_NO = "CS2026101904220000070012"
SECRET_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
SENSITIVE_SUMMARY = (
    "客户张三反馈导出报表崩溃，手机 13812345678，座机 028-87654321，邮箱 zhangsan@example.com，"
    "身份证 51010119900101123X，银行卡 6222 0212 3456 7890 123，"
    "地址：四川省成都市高新区天府大道1700号5栋302室，"
    "收货地址在四川省成都市武侯区人民南路4段12号，"
    f"user_id=70012 tenant_id: 70012 session_id=12，token={SECRET_TOKEN} "
    "password: hunter2pass Authorization: Bearer abc.def.ghi "
    "api_key=sk-" + "abcdefghijklmnop1234 接口 https://bob:pa55@intra.example.com/x "
    "密钥：Zx9QwErTy12345 服务器 10.2.3.4，复现：点导出 → 500。commit " + "a" * 40
)
CUSTOMER_FRAGMENTS = (
    "张三",
    "13812345678",
    "87654321",
    "zhangsan@example.com",
    "51010119900101123X",
    "6222 0212 3456 7890 123",
    "天府大道1700号",
    "人民南路4段12号",
    "70012",
    SECRET_TOKEN,
    "hunter2pass",
    "abc.def.ghi",
    "abcdefghijklmnop1234",
    "pa55",
    "Zx9QwErTy12345",
    "10.2.3.4",
)


def _incident(**over):
    base = {
        "ticket_id": 40,
        "ticket_no": TICKET_NO,
        "user_id": 70012,
        "tenant_id": 70012,
        "session_id": 12,
        "title": "导出报表崩溃",
        "summary": "导出报表时返回 500",
        "intent": "product_issue",
        "issue_domain": "platform",
        "scope": "fhd",
        "source": "customer_ticket",
        "product_version": "1.2.3.4",
        "git_sha": "b" * 40,
        "contact_name": "张三",
        "support_bundle_base64": "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=",
        "customer_instance_id": "inst-secret-77",
    }
    return {**base, **over}


def _req(incident=None, *, employee_id="vibe-coding-maintainer", tool="dolt", **raw):
    input_data = {
        "event_type": "ops.intake.customer_ticket",
        "role": "fix",
        "incident": incident or _incident(),
        "device_id": "dot-dev",
        "tool_name": tool,
        "allow_tool_fallback": "0",
        **raw,
    }
    return mod._build_request(
        task="修复客户问题 原文", input_data=input_data, employee_id=employee_id
    )


def _payload(req):
    return {
        "device_id": "dot-dev",
        "title": req["title"],
        "prompt": "原始提示 " + SENSITIVE_SUMMARY,
        "branch": "main",
        "subtask_title": "code: " + req["title"],
        "report_only": bool(req["report_only"]),
        "max_attempts": 3,
        "tool_name": "dolt",
        "repo_url": "https://example.com/repo.git",
        "auto_merge": True,
        "workspace_path": "/opt/xcmax/current",
    }


def _dot_mode(payload):
    text = payload["title"] + "\n" + payload["prompt"]
    if DOT_ACCOUNT.search(text) or DOT_REPORT_ONLY.search(text):
        return "report_only"
    return "code_fix"


def test_product_issue_gets_control_marker_and_code_fix_mode():
    req = _req()
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    assert MARKER.match(out["title"])
    assert "[dot:code_fix]" in out["title"] and TICKET_NO in out["title"]
    assert out["report_only"] is False and _dot_mode(out) == "code_fix"
    assert "auto_merge" not in out and "workspace_path" not in out
    assert out["tool_name"] == "dolt" and out["repo_url"] == "https://example.com/repo.git"
    assert len(out["title"]) <= 240 and len(out["prompt"]) <= 12000
    assert "原始提示" not in out["prompt"] and "修复客户问题 原文" not in out["prompt"]
    assert "intent=product_issue" in out["prompt"]
    assert "- git_sha: " + "b" * 40 in out["prompt"]
    assert "- product_version: 1.2.3.4" in out["prompt"]
    assert "MODSTORE_CREDENTIAL_GRANT" not in out["prompt"]


def test_marker_task_part_is_stable_per_ticket_and_attempt_part_unique():
    req = _req()
    first = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")["title"]
    second = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")["title"]
    assert first[:40] == second[:40] and first[:73] != second[:73]


@pytest.mark.parametrize(
    "incident_over",
    [
        {"intent": "account_support"},
        {"summary": "登录后一直转圈"},
        {"summary": "忘记密码收不到验证码"},
        {"title": "子账号权限不对"},
        {"summary": "sign in fails with 403 forbidden"},
        {"intent": "refund"},
        {"intent": "general"},
        {"intent": ""},
    ],
)
def test_account_and_non_defect_tickets_are_report_only(incident_over):
    req = _req(_incident(**incident_over))
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    assert MARKER.match(out["title"]) and "[dot:report_only]" in out["title"]
    assert out["report_only"] is True and _dot_mode(out) == "report_only"
    assert "report_only: true" in out["prompt"] and "仅出报告" in out["prompt"]


def test_scout_or_verify_role_stays_report_only():
    req = _req(employee_id="change-request-auditor")
    assert req["report_only"] is True
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    assert out["report_only"] is True and "[dot:report_only]" in out["title"]


def test_redaction_covers_every_sensitive_field():
    req = _req(_incident(summary=SENSITIVE_SUMMARY, title="张三的工单 13812345678"))
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    exported = out["title"] + "\n" + out["prompt"] + "\n" + out["subtask_title"]
    # 工单号按要求保留；去掉工单号后再查客户片段。
    without_ticket_no = exported.replace(TICKET_NO, "")
    for fragment in CUSTOMER_FRAGMENTS:
        assert fragment not in without_ticket_no, fragment
    for kind in ("手机号", "电话", "邮箱", "身份证", "银行卡", "地址", "内部ID", "凭据", "IP"):
        assert f"[已遮蔽:{kind}]" in exported, kind
    assert "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo" not in exported
    assert "inst-secret-77" not in exported
    assert not DOT_REJECT.search(exported), "dot 桥会以 possible_secret 拒收"
    assert TICKET_NO in exported and "a" * 40 in exported
    assert "复现：点导出 → 500" in exported


def test_redaction_masks_env_secret_values(monkeypatch):
    monkeypatch.setenv("MODSTORE_FAKE_API_TOKEN", "envsecretvalue-123456")
    text = dot.redact_ticket_text("报错里带了 envsecretvalue-123456 这串")
    assert "envsecretvalue-123456" not in text


def test_redaction_keeps_ordinary_text_and_short_numbers():
    text = "版本 4.10 点击第 3 个按钮后白屏，modstore_server/para_delegate_handler_part04 报错"
    assert dot.redact_ticket_text(text, sensitive_values=["12", "7"]) == text


def test_non_dolt_and_non_ticket_payloads_unchanged():
    req = _req(tool="grok_bot")
    payload = {**_payload(req), "tool_name": "grok_bot"}
    for tool in ("grok_bot", "codex", "cursor", "claude_code", "trae", ""):
        assert dot.prepare_dolt_ticket_payload(req, dict(payload), tool) == payload
    maint = mod._build_request(
        task="self maintenance", input_data={"event_type": "self_maintenance"}, employee_id="x"
    )
    plain = {"title": "self maintenance", "prompt": "p", "report_only": False}
    assert dot.prepare_dolt_ticket_payload(maint, dict(plain), "dolt") == plain


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.content = b"x"
        self.text = ""

    def json(self):
        return self._body


class _Client:
    def __init__(self, tool):
        self.tool = tool
        self.posted = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        if url.endswith("/api/devices"):
            device = {
                "id": "dot-dev",
                "status": "online",
                "tools": [{"toolName": self.tool, "status": "idle"}],
            }
            return _Resp({"devices": [device]})
        return _Resp({}, 404)

    def post(self, url, headers=None, json=None):
        if url.endswith("/api/tasks"):
            self.posted.append(json)
            return _Resp({"task": {"id": "t1", "status": "running"}, "subtask": {"id": "s1"}})
        return _Resp({}, 404)


def _env(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_API_BASE", "http://para")
    monkeypatch.setenv("MODSTORE_PARA_AUTH_TOKEN", "tok")
    monkeypatch.setenv("MODSTORE_PARA_REPO_URL", "https://example.com/repo.git")
    monkeypatch.setenv("MODSTORE_PARA_DISABLE_AUTO_RETRY", "0")
    monkeypatch.setenv("MODSTORE_PARA_SKIP_GIT_PREFLIGHT", "1")
    monkeypatch.delenv("MODSTORE_PARA_DELEGATE_WEBHOOK", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_TICKET_ROUTE", raising=False)


@pytest.mark.parametrize("tool", ["dolt", "grok_bot"])
def test_dispatch_end_to_end_only_dolt_payload_rewritten(monkeypatch, tool):
    _env(monkeypatch)
    client = _Client(tool)
    monkeypatch.setattr(mod.httpx, "Client", lambda *a, **k: client)
    incident = _incident(summary=SENSITIVE_SUMMARY)
    input_data = {
        "event_type": "ops.intake.customer_ticket",
        "role": "fix",
        "incident": incident,
        "device_id": "dot-dev",
        "tool_name": tool,
        "allow_tool_fallback": "0",
        "wait_for_para": False,
        "prompt": "原始提示 " + SENSITIVE_SUMMARY,
    }
    out = mod.dispatch_para_delegate(
        task="修复客户问题", input_data=input_data, employee_id="vibe-coding-maintainer"
    )
    assert out["ok"] is True and len(client.posted) == 1
    sent = client.posted[0]
    assert sent["tool_name"] == tool
    if tool == "dolt":
        # 摘要含 password 等字样 → 账号类，只出报告
        assert MARKER.match(sent["title"]) and sent["report_only"] is True
        assert "13812345678" not in sent["prompt"] and SECRET_TOKEN not in sent["prompt"]
        assert not DOT_REJECT.search(sent["title"] + sent["prompt"])
    else:
        assert not MARKER.match(sent["title"])
        assert sent["prompt"].startswith("原始提示 ")
        assert sent["title"] == "修复客户问题"


def test_ticket_route_hop_to_dolt_is_marked(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("MODSTORE_PARA_TICKET_ROUTE", "grok_bot@grok-dev,dolt@dot-dev")
    client = _Client("dolt")
    monkeypatch.setattr(mod.httpx, "Client", lambda *a, **k: client)
    req = mod._build_request(
        task="修复客户问题",
        input_data={
            "event_type": "ops.intake.customer_ticket",
            "incident": _incident(intent="account_support"),
            "wait_for_para": False,
        },
        employee_id="vibe-coding-maintainer",
    )
    hop = req["raw_input"]["_ticket_route"][1]
    out = mod._post_ticket_route(req, [hop])
    assert out["ok"] is True
    sent = client.posted[0]
    assert MARKER.match(sent["title"]) and "[dot:report_only]" in sent["title"]
    assert sent["report_only"] is True and sent["device_id"] == "dot-dev"


def test_mode_follows_triage_intervention():
    blocked = _req(_incident(triage_intervention={"allow_code_fix": False, "by": "grok_bot"}))
    assert blocked["raw_input"]["allow_code_fix"] is False
    out = dot.prepare_dolt_ticket_payload(blocked, _payload(blocked), "dolt")
    assert "[dot:report_only]" in out["title"] and out["report_only"] is True

    regraded = _req(
        _incident(intent="general", triage_intervention={"intent": "product_issue", "by": "dot"})
    )
    out = dot.prepare_dolt_ticket_payload(regraded, _payload(regraded), "dolt")
    assert "[dot:code_fix]" in out["title"] and "intent=product_issue" in out["prompt"]
    assert "triage_lane=product_defect" in out["prompt"]


def test_account_ticket_cannot_be_promoted_to_code_fix_by_intervention():
    req = _req(
        _incident(
            intent="account_support",
            triage_intervention={"intent": "product_issue", "allow_code_fix": True},
        )
    )
    out = dot.prepare_dolt_ticket_payload(req, _payload(req), "dolt")
    assert "[dot:report_only]" in out["title"] and out["report_only"] is True
