# -*- coding: utf-8 -*-
"""真实行为测试：app/mod_sdk/employee_specialized_tools.py。

覆盖 52 个员工专属工具的业务逻辑——参数构造、分支选择、错误处理、返回结构。
外部依赖（subprocess / httpx / 文件系统）用 monkeypatch 注入，但断言**业务结果**：

- `_run_cmd` 被替换为可断言收到的 argv / cwd / env / timeout 的 fake，
  并让工具基于伪造的 returncode/stdout 走真实分支。
- httpx 被替换为 fake AsyncClient，断言工具构造的 URL / headers / payload 与解析逻辑。
- 文件系统工具用 tmp_path + monkeypatch 路径常量，断言真实读写结果。

不做凑覆盖率 stub：每个测试都验证返回值/副作用/分支。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.mod_sdk import employee_specialized_tools as est

# ---------------------------------------------------------------------------
# 通用 fake：可断言的 _run_cmd / httpx
# ---------------------------------------------------------------------------


class _FakeRunCmd:
    """记录每次 _run_cmd 调用，并返回预设结果。"""

    def __init__(self, result: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.result = result or {"returncode": 0, "stdout": "", "stderr": "", "ok": True}
        # 允许按调用序列返回不同结果
        self.results: list[dict[str, Any]] | None = None

    async def __call__(self, args, *, cwd=None, timeout=est._DEFAULT_TIMEOUT, env=None):
        self.calls.append(
            {"args": list(args), "cwd": cwd, "timeout": timeout, "env": dict(env or {})}
        )
        if self.results is not None:
            return self.results.pop(0)
        return self.result


def _install_run_cmd(monkeypatch, result=None) -> _FakeRunCmd:
    fake = _FakeRunCmd(result)
    monkeypatch.setattr(est, "_run_cmd", fake)
    return fake


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", raise_json=False):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self._raise_json = raise_json

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._json


class _FakeAsyncClient:
    """fake httpx.AsyncClient，记录请求并返回脚本化响应。"""

    instances: list[_FakeAsyncClient] = []

    def __init__(self, *, timeout=None, **_kw):
        self.timeout = timeout
        self.requests: list[dict[str, Any]] = []
        self._responder = _FakeAsyncClient._responder
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kw):
        self.requests.append({"method": method, "url": url, **kw})
        return self._responder(method, url, kw)

    async def get(self, url, **kw):
        return await self.request("GET", url, **kw)

    async def post(self, url, **kw):
        return await self.request("POST", url, **kw)

    # 默认响应器：成功空 body
    _responder = staticmethod(lambda method, url, kw: _FakeResp(200, {}))


def _install_httpx(monkeypatch, responder):
    _FakeAsyncClient.instances = []
    _FakeAsyncClient._responder = staticmethod(responder)

    class _Mod:
        AsyncClient = _FakeAsyncClient

        @staticmethod
        def get(url, **kw):  # 同步 get（cursor/trae 用 httpx.get）
            return responder("GET", url, kw)

    monkeypatch.setattr(est, "httpx", _Mod)
    return _Mod


# ---------------------------------------------------------------------------
# _ok / _err 基础构造
# ---------------------------------------------------------------------------


def test_ok_truncates_summary_and_merges_extra():
    out = est._ok("x" * 5000, foo="bar", n=3)
    assert out["ok"] is True
    assert len(out["summary"]) == 4000
    assert out["foo"] == "bar"
    assert out["n"] == 3


def test_err_truncates_error_and_merges_extra():
    out = est._err("e" * 2000, requires_confirm=True)
    assert out["ok"] is False
    assert len(out["error"]) == 1000
    assert out["requires_confirm"] is True


# ---------------------------------------------------------------------------
# _run_cmd（真实 subprocess——用真实命令验证编解码与异常分支）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cmd_success_decodes_stdout():
    r = await est._run_cmd(["printf", "hello"])
    assert r["ok"] is True
    assert r["returncode"] == 0
    assert r["stdout"] == "hello"


@pytest.mark.asyncio
async def test_run_cmd_nonzero_returncode():
    r = await est._run_cmd(["sh", "-c", "exit 7"])
    assert r["ok"] is False
    assert r["returncode"] == 7


@pytest.mark.asyncio
async def test_run_cmd_file_not_found_branch():
    r = await est._run_cmd(["this-binary-does-not-exist-xyz"])
    assert r["ok"] is False
    assert r["returncode"] == -1
    assert r["stderr"]


@pytest.mark.asyncio
async def test_run_cmd_timeout_branch():
    r = await est._run_cmd(["sleep", "5"], timeout=1)
    assert r["ok"] is False
    assert "timeout after 1s" in r["stderr"]


# ---------------------------------------------------------------------------
# _api_call（真实 httpx 分支：未安装 / 成功 JSON / 非 JSON / 异常）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_call_httpx_missing(monkeypatch):
    monkeypatch.setattr(est, "httpx", None)
    r = await est._api_call("GET", "/x")
    assert r == {"ok": False, "error": "httpx 未安装"}


@pytest.mark.asyncio
async def test_api_call_builds_url_and_parses_json(monkeypatch):
    captured: dict[str, Any] = {}

    def responder(method, url, kw):
        captured["method"] = method
        captured["url"] = url
        return _FakeResp(200, {"hello": "world"})

    _install_httpx(monkeypatch, responder)
    r = await est._api_call("GET", "/api/health", api_base="http://host:9/")
    # base 末尾 / 被剥离，path 直接拼接
    assert captured["url"] == "http://host:9/api/health"
    assert r == {"ok": True, "status": 200, "body": {"hello": "world"}}


@pytest.mark.asyncio
async def test_api_call_path_without_leading_slash(monkeypatch):
    captured: dict[str, Any] = {}

    def responder(method, url, kw):
        captured["url"] = url
        return _FakeResp(200, {})

    _install_httpx(monkeypatch, responder)
    await est._api_call("GET", "noslash", api_base="http://h")
    assert captured["url"] == "http://h/noslash"


@pytest.mark.asyncio
async def test_api_call_non_json_falls_back_to_text(monkeypatch):
    _install_httpx(monkeypatch, lambda m, u, kw: _FakeResp(500, raise_json=True, text="boom"))
    r = await est._api_call("GET", "/x")
    assert r["ok"] is False
    assert r["status"] == 500
    assert r["body"] == "boom"


@pytest.mark.asyncio
async def test_api_call_exception_branch(monkeypatch):
    def boom(method, url, kw):
        raise RuntimeError("connect failed")

    _install_httpx(monkeypatch, boom)
    r = await est._api_call("GET", "/x")
    assert r["ok"] is False
    assert "connect failed" in r["error"]


# ---------------------------------------------------------------------------
# 质量工具：参数构造 + 分支
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_pytest_default_args_and_env(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "5 passed", "stderr": "", "ok": True}
    )
    r = await est.tool_run_pytest({}, {})
    call = fake.calls[0]
    # 默认 args 注入 pytest 命令
    assert call["args"][:3] == [est._PYTHON, "-m", "pytest"]
    assert "tests/" in call["args"]
    # 强制跳过 legacy compat routes
    assert call["env"]["XCAGI_SKIP_LEGACY_COMPAT_ROUTES"] == "1"
    assert call["timeout"] == 600
    assert r["passed"] is True
    assert r["returncode"] == 0
    assert "5 passed" in r["stdout"]


@pytest.mark.asyncio
async def test_run_pytest_string_args_split_and_custom_env(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    await est.tool_run_pytest({"args": "tests/foo -x", "env": {"EXTRA": "1"}, "timeout": 30}, {})
    call = fake.calls[0]
    assert call["args"][-2:] == ["tests/foo", "-x"]
    assert call["env"]["EXTRA"] == "1"
    assert call["env"]["XCAGI_SKIP_LEGACY_COMPAT_ROUTES"] == "1"
    assert call["timeout"] == 30


@pytest.mark.asyncio
async def test_run_pytest_failure_branch(monkeypatch):
    _install_run_cmd(
        monkeypatch, {"returncode": 1, "stdout": "1 failed", "stderr": "err", "ok": False}
    )
    r = await est.tool_run_pytest({}, {})
    assert r["passed"] is False
    assert r["returncode"] == 1


@pytest.mark.asyncio
async def test_run_ruff_check_default_and_string_targets(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    await est.tool_run_ruff_check({}, {})
    assert "app/" in fake.calls[0]["args"] and "tests/" in fake.calls[0]["args"]
    assert fake.calls[0]["args"][:4] == [est._PYTHON, "-m", "ruff", "check"]

    fake2 = _install_run_cmd(monkeypatch)
    await est.tool_run_ruff_check({"targets": "app/x app/y"}, {})
    assert fake2.calls[0]["args"][-2:] == ["app/x", "app/y"]


@pytest.mark.asyncio
async def test_run_ruff_format_check_flag(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    r = await est.tool_run_ruff_format({"targets": ["app/"]}, {})
    assert fake.calls[0]["args"][:5] == [est._PYTHON, "-m", "ruff", "format", "--check"]
    assert r["passed"] is True


@pytest.mark.asyncio
async def test_run_mypy_default_and_timeout(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    await est.tool_run_mypy({}, {})
    assert fake.calls[0]["args"][:3] == [est._PYTHON, "-m", "mypy"]
    assert "app/" in fake.calls[0]["args"]
    assert fake.calls[0]["timeout"] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,script_substr",
    [
        (est.tool_check_coverage, "coverage_ratchet.py"),
        (est.tool_count_type_debt, "count_type_debt.py"),
        (est.tool_count_raw_sql, "count_raw_sql.py"),
        (est.tool_run_arch_fitness, "arch_fitness.py"),
        (est.tool_verify_version_anchors, "verify_version_anchors.py"),
        (est.tool_verify_employee_contract, "verify_employee_contract.py"),
        (est.tool_mutation_kill_report, "mutation_kill_report.py"),
    ],
)
async def test_script_running_quality_tools(monkeypatch, tool, script_substr):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "out", "stderr": "", "ok": True}
    )
    r = await tool({}, {})
    # 第一个 arg 是 python，第二个是脚本路径
    script_arg = fake.calls[0]["args"][1]
    assert script_substr in script_arg
    assert r["ok"] is True
    assert r["passed"] is True


# ---------------------------------------------------------------------------
# Git 工具
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_git_status_parses_changes(monkeypatch):
    _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": " M a.py\n?? b.py\n\n", "stderr": "", "ok": True}
    )
    r = await est.tool_git_status({}, {})
    assert r["files"] == [" M a.py", "?? b.py"]
    assert r["clean"] is False


@pytest.mark.asyncio
async def test_git_status_clean(monkeypatch):
    _install_run_cmd(monkeypatch, {"returncode": 0, "stdout": "", "stderr": "", "ok": True})
    r = await est.tool_git_status({}, {})
    assert r["clean"] is True
    assert r["files"] == []


@pytest.mark.asyncio
async def test_git_log_n_param(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "a c1\nb c2\n", "stderr": "", "ok": True}
    )
    r = await est.tool_git_log({"n": 5}, {})
    assert fake.calls[0]["args"] == ["git", "log", "--oneline", "-5"]
    assert r["commits"] == ["a c1", "b c2"]


@pytest.mark.asyncio
async def test_git_diff_with_ref_and_stat(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "diffbody", "stderr": "", "ok": True}
    )
    r = await est.tool_git_diff({"ref": "HEAD~1", "stat": True}, {})
    assert fake.calls[0]["args"] == ["git", "diff", "HEAD~1", "--stat"]
    assert r["diff"] == "diffbody"


@pytest.mark.asyncio
async def test_git_diff_no_ref(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    await est.tool_git_diff({}, {})
    assert fake.calls[0]["args"] == ["git", "diff"]


@pytest.mark.asyncio
async def test_git_branch(monkeypatch):
    _install_run_cmd(monkeypatch, {"returncode": 0, "stdout": "feat/x\n", "stderr": "", "ok": True})
    r = await est.tool_git_branch({}, {})
    assert r["branch"] == "feat/x"
    assert "feat/x" in r["summary"]


# ---------------------------------------------------------------------------
# 部署工具：confirm gate + 参数校验
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pack_release_requires_confirm(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    r = await est.tool_pack_release({}, {})
    assert r["ok"] is False
    assert r["requires_confirm"] is True
    assert fake.calls == []  # 未确认绝不执行命令


@pytest.mark.asyncio
async def test_pack_release_confirmed_runs_bash(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "packed", "stderr": "", "ok": True}
    )
    r = await est.tool_pack_release({"confirm": True}, {})
    assert fake.calls[0]["args"][0] == "bash"
    assert "fhd-pack-release.sh" in fake.calls[0]["args"][1]
    assert r["passed"] is True


@pytest.mark.asyncio
async def test_list_deploy_scripts_reads_dir(monkeypatch, tmp_path):
    deploy = tmp_path / "scripts" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "b.sh").write_text("x")
    (deploy / "a.sh").write_text("x")
    (deploy / "ignore.py").write_text("x")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_list_deploy_scripts({}, {})
    assert r["scripts"] == ["a.sh", "b.sh"]


@pytest.mark.asyncio
async def test_trigger_gh_workflow_confirm_and_missing_workflow(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    # 无 confirm
    assert (await est.tool_trigger_gh_workflow({}, {}))["requires_confirm"] is True
    # confirm 但缺 workflow
    r2 = await est.tool_trigger_gh_workflow({"confirm": True}, {})
    assert r2["ok"] is False and "缺少 workflow" in r2["error"]
    assert fake.calls == []


@pytest.mark.asyncio
async def test_trigger_gh_workflow_runs_with_ref(monkeypatch):
    fake = _install_run_cmd(monkeypatch, {"returncode": 0, "stdout": "", "stderr": "", "ok": True})
    await est.tool_trigger_gh_workflow({"confirm": True, "workflow": "ci.yml", "ref": "dev"}, {})
    assert fake.calls[0]["args"] == ["gh", "workflow", "run", "ci.yml", "--ref", "dev"]


# ---------------------------------------------------------------------------
# 基础设施工具
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nginx_test_not_installed(monkeypatch):
    monkeypatch.setattr(est.shutil, "which", lambda _: None)
    r = await est.tool_nginx_test({}, {})
    assert r["skipped"] is True
    assert r["syntax_valid"] is None


@pytest.mark.asyncio
async def test_nginx_test_installed_runs(monkeypatch):
    monkeypatch.setattr(est.shutil, "which", lambda _: "/usr/bin/nginx")
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "ok", "stderr": "", "ok": True}
    )
    r = await est.tool_nginx_test({}, {})
    assert fake.calls[0]["args"] == ["/usr/bin/nginx", "-t"]
    assert r["syntax_valid"] is True


@pytest.mark.asyncio
async def test_api_health_uses_ctx_base(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["path"] = path
        captured["api_base"] = api_base
        return {"ok": True, "status": 200, "body": {"status": "up"}}

    monkeypatch.setattr(est, "_api_call", fake_api)
    r = await est.tool_api_health({}, {"api_base": "http://ctxhost"})
    assert captured["path"] == "/api/health"
    assert captured["api_base"] == "http://ctxhost"
    assert r["status"] == 200


@pytest.mark.asyncio
async def test_api_health_param_overrides_ctx(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["api_base"] = api_base
        return {"ok": True, "status": 200}

    monkeypatch.setattr(est, "_api_call", fake_api)
    await est.tool_api_health({"api_base": "http://param"}, {"api_base": "http://ctx"})
    assert captured["api_base"] == "http://param"


@pytest.mark.asyncio
async def test_disk_usage(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "Filesystem ...", "stderr": "", "ok": True}
    )
    r = await est.tool_disk_usage({}, {})
    assert fake.calls[0]["args"][:2] == ["df", "-h"]
    assert "Filesystem" in r["output"]


@pytest.mark.asyncio
async def test_tail_logs_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)  # 无 logs 目录
    r = await est.tool_tail_logs({}, {})
    assert r["lines"] == []
    assert "logs 目录不存在" in r["summary"]


@pytest.mark.asyncio
async def test_tail_logs_missing_file_lists_available(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "other.log").write_text("x")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_tail_logs({"file": "app.log"}, {})
    assert r["available_files"] == ["other.log"]


@pytest.mark.asyncio
async def test_tail_logs_reads_last_n(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("\n".join(f"line{i}" for i in range(10)))
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_tail_logs({"lines": 3}, {})
    assert r["lines"] == ["line7", "line8", "line9"]


# ---------------------------------------------------------------------------
# mod / 员工包工具：真实文件系统
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_employee_packs_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", tmp_path / "missing")
    r = await est.tool_list_employee_packs({}, {})
    assert r["packs"] == []


@pytest.mark.asyncio
async def test_list_employee_packs_parses_manifests(monkeypatch, tmp_path):
    emp = tmp_path / "_employees"
    (emp / "alpha").mkdir(parents=True)
    (emp / "alpha" / "manifest.json").write_text(
        json.dumps(
            {
                "id": "alpha-id",
                "name": "Alpha",
                "artifact": "employee_pack",
                "employee_config_v2": {"area": "platform-core"},
            }
        )
    )
    # 损坏的 manifest 应被跳过
    (emp / "broken").mkdir()
    (emp / "broken" / "manifest.json").write_text("{not json")
    # 无 manifest 的目录应被跳过
    (emp / "nomf").mkdir()
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", emp)
    r = await est.tool_list_employee_packs({}, {})
    assert len(r["packs"]) == 1
    pack = r["packs"][0]
    assert pack["id"] == "alpha-id"
    assert pack["label"] == "Alpha"
    assert pack["area"] == "platform-core"


@pytest.mark.asyncio
async def test_validate_employee_pack_missing_id(monkeypatch):
    r = await est.tool_validate_employee_pack({}, {})
    assert r["ok"] is False and "缺少 pack_id" in r["error"]


@pytest.mark.asyncio
async def test_validate_employee_pack_manifest_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", tmp_path)
    r = await est.tool_validate_employee_pack({"pack_id": "ghost"}, {})
    assert r["ok"] is False and "manifest 不存在" in r["error"]


@pytest.mark.asyncio
async def test_validate_employee_pack_valid(monkeypatch, tmp_path):
    pid = "good"
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "manifest.json").write_text(
        json.dumps(
            {
                "id": pid,
                "artifact": "employee_pack",
                "employee_config_v2": {"cognition": {"agent": {"system_prompt": "you are good"}}},
            }
        )
    )
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", tmp_path)
    r = await est.tool_validate_employee_pack({"pack_id": pid}, {})
    assert r["valid"] is True
    assert r["issues"] == []


@pytest.mark.asyncio
async def test_validate_employee_pack_collects_issues(monkeypatch, tmp_path):
    pid = "bad"
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "manifest.json").write_text(
        json.dumps({"artifact": "wrong", "employee_config_v2": {"cognition": {}}})
    )
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", tmp_path)
    r = await est.tool_validate_employee_pack({"pack_id": pid}, {})
    assert r["valid"] is False
    joined = " ".join(r["issues"])
    assert "artifact 应为 employee_pack" in joined
    assert "缺少 id" in joined
    assert "缺少 system_prompt" in joined


@pytest.mark.asyncio
async def test_validate_employee_pack_bad_json(monkeypatch, tmp_path):
    pid = "corrupt"
    (tmp_path / pid).mkdir()
    (tmp_path / pid / "manifest.json").write_text("{broken")
    monkeypatch.setattr(est, "_EMPLOYEES_DIR", tmp_path)
    r = await est.tool_validate_employee_pack({"pack_id": pid}, {})
    assert r["ok"] is False and "解析失败" in r["error"]


# ---------------------------------------------------------------------------
# 文档工具
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_docs(monkeypatch, tmp_path):
    root = tmp_path / "FHD"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("x")
    (root / "docs" / "sub").mkdir()
    (root / "docs" / "sub" / "b.md").write_text("x")
    monkeypatch.setattr(est, "_FHD_ROOT", root)
    r = await est.tool_list_docs({}, {})
    assert any(d.endswith("a.md") for d in r["docs"])
    assert any(d.endswith("b.md") for d in r["docs"])


@pytest.mark.asyncio
async def test_read_file_missing_path():
    r = await est.tool_read_file({}, {})
    assert r["ok"] is False and "缺少 path" in r["error"]


@pytest.mark.asyncio
async def test_read_file_path_traversal_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_read_file({"path": "../../etc/passwd"}, {})
    assert r["ok"] is False and "越界" in r["error"]


@pytest.mark.asyncio
async def test_read_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_read_file({"path": "nope.txt"}, {})
    assert r["ok"] is False and "文件不存在" in r["error"]


@pytest.mark.asyncio
async def test_read_file_success(monkeypatch, tmp_path):
    (tmp_path / "f.txt").write_text("content-123")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_read_file({"path": "f.txt"}, {})
    assert r["ok"] is True
    assert r["content"] == "content-123"
    assert r["truncated"] is False
    assert r["path"] == "f.txt"


@pytest.mark.asyncio
async def test_list_scripts_categories(monkeypatch, tmp_path):
    s = tmp_path / "scripts"
    (s / "dev").mkdir(parents=True)
    (s / "dev" / "x.py").write_text("x")
    (s / "deploy.sh").write_text("x")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    # 全量
    r = await est.tool_list_scripts({}, {})
    assert any(p.endswith("x.py") for p in r["python"])
    assert any(p.endswith("deploy.sh") for p in r["shell"])
    # 指定 category
    r2 = await est.tool_list_scripts({"category": "dev"}, {})
    assert any(p.endswith("x.py") for p in r2["python"])
    assert r2["shell"] == []
    # 不存在的 category
    r3 = await est.tool_list_scripts({"category": "ghost"}, {})
    assert r3["ok"] is False and "目录不存在" in r3["error"]


@pytest.mark.asyncio
async def test_list_scripts_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)  # 无 scripts 目录
    r = await est.tool_list_scripts({}, {})
    assert r["scripts"] == []


# ---------------------------------------------------------------------------
# 平台工具：duty_roster 解析（含递归 subzones）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_employees_missing_roster(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_DUTY_ROSTER", tmp_path / "missing.json")
    r = await est.tool_list_employees({}, {})
    assert r["ok"] is False and "不存在" in r["error"]


@pytest.mark.asyncio
async def test_list_employees_recursive_collect(monkeypatch, tmp_path):
    roster = tmp_path / "duty_roster.json"
    roster.write_text(
        json.dumps(
            {
                "areas": {
                    "a1": {
                        "ids": ["e1", "e2", ""],
                        "subzones": {"sz": {"ids": ["e3"]}},
                    },
                    "broken": "not-a-dict",
                },
                "departments": {"d1": {"ids": ["e2", "e4"]}},
            }
        )
    )
    monkeypatch.setattr(est, "_DUTY_ROSTER", roster)
    r = await est.tool_list_employees({}, {})
    # 去重 + 排序 + 空串过滤；e3 来自 subzones（递归）
    assert r["employees"] == ["e1", "e2", "e3", "e4"]


@pytest.mark.asyncio
async def test_list_employees_bad_json(monkeypatch, tmp_path):
    roster = tmp_path / "duty_roster.json"
    roster.write_text("{bad")
    monkeypatch.setattr(est, "_DUTY_ROSTER", roster)
    r = await est.tool_list_employees({}, {})
    assert r["ok"] is False and "解析失败" in r["error"]


@pytest.mark.asyncio
async def test_employee_status_missing_id():
    r = await est.tool_employee_status({}, {})
    assert r["ok"] is False and "缺少 employee_id" in r["error"]


@pytest.mark.asyncio
async def test_employee_status_uses_id_in_path(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["path"] = path
        return {"ok": True, "status": 200, "body": {}}

    monkeypatch.setattr(est, "_api_call", fake_api)
    r = await est.tool_employee_status({"employee_id": "emp7"}, {})
    assert "/employees/emp7/status" in captured["path"]
    assert r["employee_id"] == "emp7"


@pytest.mark.asyncio
async def test_employee_status_id_from_ctx(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["path"] = path
        return {"ok": True, "status": 200}

    monkeypatch.setattr(est, "_api_call", fake_api)
    await est.tool_employee_status({}, {"employee_id": "ctx-emp"})
    assert "ctx-emp" in captured["path"]


# ---------------------------------------------------------------------------
# API 直通工具：断言路径与查询参数
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,expected_path",
    [
        (est.tool_mod_loading_status, "/api/mods/loading-status"),
        (est.tool_performance_status, "/api/performance/status"),
        (est.tool_list_mods, "/api/mods/"),
        (est.tool_duty_graph_health, "/api/xcmax/ops/duty-health"),
        (est.tool_list_action_items, "/api/admin/action-items"),
        (est.tool_employee_autonomy_dashboard, "/api/admin/employee-autonomy/dashboard"),
        (est.tool_list_invoices, "/api/admin/invoices"),
        (est.tool_list_enterprise_mods, "/api/admin/enterprise/assignable-mods"),
        (est.tool_list_users, "/api/admin/users"),
    ],
)
async def test_passthrough_api_tools(monkeypatch, tool, expected_path):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["method"] = method
        captured["path"] = path
        return {"ok": True, "status": 200, "body": {"x": 1}}

    monkeypatch.setattr(est, "_api_call", fake_api)
    r = await tool({}, {})
    assert captured["method"] == "GET"
    assert captured["path"] == expected_path
    assert r["status"] == 200


@pytest.mark.asyncio
async def test_check_transactions_passes_limit(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_api(method, path, *, api_base=None, **kw):
        captured["path"] = path
        captured["params"] = kw.get("params")
        return {"ok": True, "status": 200}

    monkeypatch.setattr(est, "_api_call", fake_api)
    await est.tool_check_transactions({"limit": 7}, {})
    assert captured["path"] == "/api/admin/wallets"
    assert captured["params"] == {"limit": 7}


# ---------------------------------------------------------------------------
# Craft 工具
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workbench_sessions_no_dir(monkeypatch, tmp_path):
    r = await est.tool_list_workbench_sessions({}, {"workspace_root": str(tmp_path)})
    assert r["sessions"] == []


@pytest.mark.asyncio
async def test_list_workbench_sessions_lists(monkeypatch, tmp_path):
    sd = tmp_path / "workbench" / "sessions"
    (sd / "s1").mkdir(parents=True)
    (sd / "s2").mkdir()
    (sd / "afile.txt").write_text("x")  # 文件应被忽略，只列目录
    r = await est.tool_list_workbench_sessions({}, {"workspace_root": str(tmp_path)})
    assert r["sessions"] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_sandbox_python_missing_code():
    r = await est.tool_sandbox_python({}, {})
    assert r["ok"] is False and "缺少 code" in r["error"]


@pytest.mark.asyncio
async def test_sandbox_python_too_long():
    r = await est.tool_sandbox_python({"code": "a" * 20001}, {})
    assert r["ok"] is False and "代码过长" in r["error"]


@pytest.mark.asyncio
async def test_sandbox_python_forbidden_without_confirm(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    r = await est.tool_sandbox_python({"code": "import os\nprint(1)"}, {})
    assert r["ok"] is False
    assert r["requires_confirm"] is True
    assert "import os" in r["error"]
    assert fake.calls == []  # 受限操作未确认不执行


@pytest.mark.asyncio
async def test_sandbox_python_forbidden_with_confirm_runs(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "1\n", "stderr": "", "ok": True}
    )
    r = await est.tool_sandbox_python({"code": "import os\nprint(1)", "confirm": True}, {})
    assert r["passed"] is True
    # 沙箱环境变量注入
    assert fake.calls[0]["env"]["XCAGI_SANDBOX"] == "1"
    assert fake.calls[0]["timeout"] == 30


@pytest.mark.asyncio
async def test_sandbox_python_safe_code_runs(monkeypatch):
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "42\n", "stderr": "", "ok": True}
    )
    r = await est.tool_sandbox_python({"code": "print(40 + 2)"}, {})
    assert r["passed"] is True
    assert fake.calls[0]["args"][:2] == [est._PYTHON, "-c"]
    assert "print(40 + 2)" in fake.calls[0]["args"][2]


# ---------------------------------------------------------------------------
# 前端工具：package.json / npm 缺失分支
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,script",
    [
        (est.tool_frontend_lint, "lint"),
        (est.tool_frontend_typecheck, "type-check"),
        (est.tool_frontend_test, "test"),
    ],
)
async def test_frontend_no_package_json(monkeypatch, tmp_path, tool, script):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)  # 无 frontend/package.json
    r = await tool({}, {})
    assert r["ok"] is False and "package.json 不存在" in r["error"]


@pytest.mark.asyncio
async def test_frontend_lint_npm_missing(monkeypatch, tmp_path):
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "package.json").write_text("{}")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    monkeypatch.setattr(est.shutil, "which", lambda _: None)
    r = await est.tool_frontend_lint({}, {})
    assert r["skipped"] is True


@pytest.mark.asyncio
async def test_frontend_test_runs_npm(monkeypatch, tmp_path):
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "package.json").write_text("{}")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    monkeypatch.setattr(est.shutil, "which", lambda _: "/usr/bin/npm")
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "ok", "stderr": "", "ok": True}
    )
    r = await est.tool_frontend_test({}, {})
    assert fake.calls[0]["args"] == ["/usr/bin/npm", "run", "test"]
    assert str(fake.calls[0]["cwd"]) == str(fe)
    assert r["passed"] is True


# ---------------------------------------------------------------------------
# 移动端工具
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_android_gradle_requires_confirm(monkeypatch):
    fake = _install_run_cmd(monkeypatch)
    r = await est.tool_android_gradle_build({}, {})
    assert r["requires_confirm"] is True
    assert fake.calls == []


@pytest.mark.asyncio
async def test_android_gradle_missing_gradlew(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_android_gradle_build({"confirm": True}, {})
    assert r["ok"] is False and "gradlew 不存在" in r["error"]


@pytest.mark.asyncio
async def test_android_gradle_runs(monkeypatch, tmp_path):
    android = tmp_path / "mobile-android"
    android.mkdir()
    (android / "gradlew").write_text("#!/bin/sh")
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    fake = _install_run_cmd(
        monkeypatch, {"returncode": 0, "stdout": "tasks", "stderr": "", "ok": True}
    )
    r = await est.tool_android_gradle_build({"confirm": True}, {})
    assert fake.calls[0]["args"][0] == "bash"
    assert "gradlew" in fake.calls[0]["args"][1]
    assert r["passed"] is True


# ---------------------------------------------------------------------------
# 代码修改工具：write_file / patch_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_requires_confirm():
    r = await est.tool_write_file({"path": "x.txt", "content": "y"}, {})
    assert r["ok"] is False and "二次确认" in r["error"]


@pytest.mark.asyncio
async def test_write_file_missing_path():
    r = await est.tool_write_file({"confirm": True}, {})
    assert r["ok"] is False and "缺少 params.path" in r["error"]


@pytest.mark.asyncio
async def test_write_file_traversal_blocked(tmp_path):
    r = await est.tool_write_file(
        {"confirm": True, "path": "../escape.txt", "content": "x"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is False and "越出 workspace_root" in r["error"]


@pytest.mark.asyncio
async def test_write_file_success(tmp_path):
    r = await est.tool_write_file(
        {"confirm": True, "path": "sub/new.txt", "content": "héllo"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is True
    target = tmp_path / "sub" / "new.txt"
    assert target.read_text(encoding="utf-8") == "héllo"
    # bytes_written 是 utf-8 编码字节数（é = 2 bytes）
    assert r["bytes_written"] == len("héllo".encode())


@pytest.mark.asyncio
async def test_patch_file_requires_confirm():
    r = await est.tool_patch_file({"path": "x", "patch": "y"}, {})
    assert r["ok"] is False and "二次确认" in r["error"]


@pytest.mark.asyncio
async def test_patch_file_missing_params():
    r = await est.tool_patch_file({"confirm": True, "path": ""}, {})
    assert r["ok"] is False and ("缺少" in r["error"])


@pytest.mark.asyncio
async def test_patch_file_traversal_blocked(tmp_path):
    r = await est.tool_patch_file(
        {"confirm": True, "path": "../x", "patch": "diff"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is False and "越出 workspace_root" in r["error"]


@pytest.mark.asyncio
async def test_patch_file_target_not_found(tmp_path):
    r = await est.tool_patch_file(
        {"confirm": True, "path": "missing.txt", "patch": "diff"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is False and "目标文件不存在" in r["error"]


@pytest.mark.asyncio
async def test_patch_file_check_failure(monkeypatch, tmp_path):
    (tmp_path / "f.txt").write_text("old\n")
    # git apply --check 失败 → 返回校验失败，不应继续 apply
    fake = _FakeRunCmd()
    fake.results = [{"returncode": 1, "stdout": "", "stderr": "patch does not apply", "ok": False}]
    monkeypatch.setattr(est, "_run_cmd", fake)
    r = await est.tool_patch_file(
        {"confirm": True, "path": "f.txt", "patch": "bad diff"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is False and "校验失败" in r["error"]
    assert len(fake.calls) == 1  # 只跑了 --check，没跑 apply
    # 临时 patch 文件已清理
    assert not list(tmp_path.glob(".tmp-patch-*.diff"))


@pytest.mark.asyncio
async def test_patch_file_apply_failure(monkeypatch, tmp_path):
    (tmp_path / "f.txt").write_text("old\n")
    fake = _FakeRunCmd()
    fake.results = [
        {"returncode": 0, "stdout": "", "stderr": "", "ok": True},  # --check ok
        {"returncode": 1, "stdout": "", "stderr": "apply boom", "ok": False},  # apply fail
    ]
    monkeypatch.setattr(est, "_run_cmd", fake)
    r = await est.tool_patch_file(
        {"confirm": True, "path": "f.txt", "patch": "diff"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is False and "应用失败" in r["error"]
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_patch_file_success(monkeypatch, tmp_path):
    (tmp_path / "f.txt").write_text("old\n")
    fake = _FakeRunCmd({"returncode": 0, "stdout": "", "stderr": "", "ok": True})
    monkeypatch.setattr(est, "_run_cmd", fake)
    r = await est.tool_patch_file(
        {"confirm": True, "path": "f.txt", "patch": "valid diff"},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is True
    assert r["path"] == "f.txt"
    # check + apply 都跑了，且 patch 文件被清理
    assert len(fake.calls) == 2
    assert not list(tmp_path.glob(".tmp-patch-*.diff"))


# ---------------------------------------------------------------------------
# _code_write_tools / _check_write_gate
# ---------------------------------------------------------------------------


def test_code_write_tools_contains_write_and_patch():
    tools = est._code_write_tools()
    assert "write_file" in tools
    assert "patch_file" in tools


@pytest.mark.asyncio
async def test_check_write_gate_exception_blocks(monkeypatch):
    # 让内部导入失败，触发 except 分支 → 阻断写操作
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if "employee_runtime" in name or "employee_registry" in name or "mod_manager" in name:
            raise ImportError("forced")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    verdict = await est._check_write_gate("emp", "write_file", {}, {})
    assert verdict["ok"] is False
    assert "gate 检查异常" in verdict["reason"]


# ---------------------------------------------------------------------------
# LLM provider helper 纯函数
# ---------------------------------------------------------------------------


def test_mask_secret():
    assert est._mask_secret("") == ""
    assert est._mask_secret("short") == "***"  # <=8
    assert est._mask_secret("sk-abc123xyz") == "sk-***xyz"


def test_read_env_file_parsing(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "OPENAI_API_KEY='sk-secret'",
                'OPENAI_MODEL="gpt-4o"',
                "noequalsline",
                "  XCAGI_LLM_PROVIDER = b.ai ",
            ]
        )
    )
    out = est._read_env_file(p)
    assert out["OPENAI_API_KEY"] == "sk-secret"  # 引号被剥离
    assert out["OPENAI_MODEL"] == "gpt-4o"
    assert out["XCAGI_LLM_PROVIDER"] == "b.ai"
    assert "noequalsline" not in out


def test_read_env_file_missing(tmp_path):
    assert est._read_env_file(tmp_path / "nope.env") == {}


def test_provider_has_key_and_base_and_model():
    profile = {
        "env_keys": ["FOO_KEY", "BAR_KEY"],
        "base_url_env": "FOO_BASE",
        "base_url_default": "https://default",
        "model_env": "FOO_MODEL",
        "default_model": "m-default",
    }
    # has_key 返回第一个非空
    assert est._provider_has_key(profile, {"BAR_KEY": "k2"}) == "k2"
    assert est._provider_has_key(profile, {}) is None
    # base_url env 覆盖 default
    assert est._provider_base_url(profile, {"FOO_BASE": "https://custom"}) == "https://custom"
    assert est._provider_base_url(profile, {}) == "https://default"
    # model env 覆盖 default
    assert est._provider_model(profile, {"FOO_MODEL": "m-x"}) == "m-x"
    assert est._provider_model(profile, {}) == "m-default"


def test_detect_provider_name():
    with_detect = {"detect": lambda env: env.get("X") == "yes", "env_keys": []}
    assert est._detect_provider_name(with_detect, {"X": "yes"}) is True
    assert est._detect_provider_name(with_detect, {"X": "no"}) is False
    # 无 detect：有 key 即匹配
    no_detect = {"env_keys": ["K"]}
    assert est._detect_provider_name(no_detect, {"K": "v"}) is True
    assert est._detect_provider_name(no_detect, {}) is False


# ---------------------------------------------------------------------------
# tool_read_llm_env_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_llm_env_config_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)  # 无 .env
    r = await est.tool_read_llm_env_config({}, {})
    assert r["ok"] is False and "不存在或为空" in r["error"]


@pytest.mark.asyncio
async def test_read_llm_env_config_masks_secrets(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-abcdefghij\nOPENAI_MODEL=gpt-4o\nXCAGI_LLM_PROVIDER=openai\n"
    )
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = await est.tool_read_llm_env_config({}, {})
    assert r["ok"] is True
    # API key 脱敏；非 secret 原样
    assert r["env_config"]["OPENAI_API_KEY"] == "sk-***hij"
    assert r["env_config"]["OPENAI_MODEL"] == "gpt-4o"
    assert r["configured_provider"] == "openai"
    assert "openai" in r["supported_providers"]


# ---------------------------------------------------------------------------
# tool_list_configured_providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_configured_providers_filters_unconfigured(monkeypatch):
    # 清掉所有 provider env，只配 deepseek
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseekkey")
    monkeypatch.setenv("XCAGI_LLM_PROVIDER", "deepseek")
    r = await est.tool_list_configured_providers({}, {})
    names = {p["provider"] for p in r["providers"]}
    # deepseek 有 key → 列出；ollama 无 auth → 也列出
    assert "deepseek" in names
    assert "ollama" in names
    # openai 无 key → 不列出
    assert "openai" not in names
    ds = next(p for p in r["providers"] if p["provider"] == "deepseek")
    assert ds["has_key"] is True
    assert ds["api_key"] == "sk-***key"
    assert r["active_provider"] == "deepseek"
    assert r["supported_count"] == len(est._PROVIDER_PROFILES)
    # ollama no_auth 标注
    ol = next(p for p in r["providers"] if p["provider"] == "ollama")
    assert ol["has_key"] is True
    assert ol["api_key"] == "(无需)"


# ---------------------------------------------------------------------------
# tool_test_llm_key_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_llm_key_health_httpx_missing(monkeypatch):
    monkeypatch.setattr(est, "httpx", None)
    r = await est.tool_test_llm_key_health({}, {})
    assert r["ok"] is False and "httpx 未安装" in r["error"]


@pytest.mark.asyncio
async def test_test_llm_key_health_no_configured(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    # 限定到一个需要 key 的 provider，且不配 → 无结果
    _install_httpx(monkeypatch, lambda m, u, kw: _FakeResp(200, {}))
    r = await est.tool_test_llm_key_health({"provider": "openai"}, {})
    assert r["ok"] is False and "未找到已配置" in r["error"]


@pytest.mark.asyncio
async def test_test_llm_key_health_ping_success(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    captured: dict[str, Any] = {}

    def responder(method, url, kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers")
        captured["json"] = kw.get("json")
        return _FakeResp(200, {"choices": []})

    _install_httpx(monkeypatch, responder)
    r = await est.tool_test_llm_key_health({"provider": "deepseek"}, {})
    assert r["ok"] is True
    assert r["healthy_count"] == 1
    assert r["total_count"] == 1
    res = r["results"][0]
    assert res["provider"] == "deepseek"
    assert res["ok"] is True
    assert res["status"] == 200
    # ping 用 ping_model（deepseek-chat），payload max_tokens=1
    assert captured["json"]["max_tokens"] == 1
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-x"


@pytest.mark.asyncio
async def test_test_llm_key_health_error_status(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    _install_httpx(monkeypatch, lambda m, u, kw: _FakeResp(401, {"error": "bad key"}))
    r = await est.tool_test_llm_key_health({"provider": "deepseek"}, {})
    res = r["results"][0]
    assert res["ok"] is False
    assert res["status"] == 401
    assert "bad key" in res["error"]
    assert r["healthy_count"] == 0


@pytest.mark.asyncio
async def test_test_llm_key_health_network_exception(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")

    def boom(method, url, kw):
        raise RuntimeError("dns fail")

    _install_httpx(monkeypatch, boom)
    r = await est.tool_test_llm_key_health({"provider": "deepseek"}, {})
    res = r["results"][0]
    assert res["ok"] is False
    assert res["status"] == 0
    assert "dns fail" in res["error"]


@pytest.mark.asyncio
async def test_test_llm_key_health_ollama_no_auth(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    captured: dict[str, Any] = {}

    def responder(method, url, kw):
        captured["headers"] = kw.get("headers")
        return _FakeResp(200, {})

    _install_httpx(monkeypatch, responder)
    r = await est.tool_test_llm_key_health({"provider": "ollama"}, {})
    assert r["ok"] is True
    # 无 auth → 不带 Authorization header
    assert "Authorization" not in captured["headers"]


# ---------------------------------------------------------------------------
# tool_query_provider_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_provider_usage_httpx_missing(monkeypatch):
    monkeypatch.setattr(est, "httpx", None)
    r = await est.tool_query_provider_usage({}, {})
    assert r["ok"] is False and "httpx 未安装" in r["error"]


@pytest.mark.asyncio
async def test_query_provider_usage_no_billing_endpoint(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    # qwen 有 key 但 billing_endpoints 为空
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-q")
    _install_httpx(monkeypatch, lambda m, u, kw: _FakeResp(200, {}))
    r = await est.tool_query_provider_usage({"provider": "qwen"}, {})
    assert r["ok"] is True
    finding = r["findings"][0]
    assert finding["provider"] == "qwen"
    assert finding["endpoint"] == "(无)"
    assert "无标准 billing API" in finding["error"]
    assert r["has_usage_api"] is False


@pytest.mark.asyncio
async def test_query_provider_usage_success(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    captured: dict[str, Any] = {}

    def responder(method, url, kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers")
        return _FakeResp(200, {"balance": 100})

    _install_httpx(monkeypatch, responder)
    r = await est.tool_query_provider_usage({"provider": "deepseek"}, {})
    assert r["ok"] is True
    assert r["has_usage_api"] is True
    finding = r["findings"][0]
    assert finding["ok"] is True
    assert finding["body"] == {"balance": 100}
    # deepseek billing endpoint /user/balance
    assert captured["url"].endswith("/user/balance")
    assert captured["headers"]["Authorization"] == "Bearer sk-d"


@pytest.mark.asyncio
async def test_query_provider_usage_request_exception(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")

    def boom(method, url, kw):
        raise RuntimeError("timeout")

    _install_httpx(monkeypatch, boom)
    r = await est.tool_query_provider_usage({"provider": "deepseek"}, {})
    finding = r["findings"][0]
    assert finding["ok"] is False
    assert finding["status"] == 0
    assert "timeout" in finding["error"]


@pytest.mark.asyncio
async def test_query_provider_usage_non_json_body(monkeypatch):
    for k in est._LLM_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-d")
    _install_httpx(
        monkeypatch, lambda m, u, kw: _FakeResp(200, raise_json=True, text="plain text body")
    )
    r = await est.tool_query_provider_usage({"provider": "deepseek"}, {})
    finding = r["findings"][0]
    # 非 dict/list → 转字符串
    assert finding["body"] == "plain text body"


# ---------------------------------------------------------------------------
# tool_compare_model_prices（纯逻辑：过滤 + 排序 + free 标注）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_model_prices_default_sort_output():
    r = await est.tool_compare_model_prices({}, {})
    assert r["ok"] is True
    assert r["sort_by"] == "output_per_1m"
    assert r["total_models"] == len(est._MODEL_PRICES)
    # 升序：第一个是最便宜（cheapest）
    outs = [float(p["output_per_1m"]) for p in r["prices"]]
    assert outs == sorted(outs)
    assert r["cheapest"] == r["prices"][0]
    # free_models 全部为 0/0
    for m in r["free_models"]:
        entry = next(p for p in r["prices"] if p["model"] == m)
        assert entry["input_per_1m"] == 0 and entry["output_per_1m"] == 0


@pytest.mark.asyncio
async def test_compare_model_prices_sort_input():
    r = await est.tool_compare_model_prices({"sort_by": "input"}, {})
    assert r["sort_by"] == "input_per_1m"
    ins = [float(p["input_per_1m"]) for p in r["prices"]]
    assert ins == sorted(ins)


@pytest.mark.asyncio
async def test_compare_model_prices_provider_filter():
    r = await est.tool_compare_model_prices({"provider": "deepseek"}, {})
    assert len(r["prices"]) >= 1
    for p in r["prices"]:
        assert "deepseek" in str(p["provider"]).lower()


@pytest.mark.asyncio
async def test_compare_model_prices_empty_filter():
    r = await est.tool_compare_model_prices({"provider": "nonexistent-provider"}, {})
    assert r["prices"] == []
    assert r["cheapest"] is None
    assert r["free_models"] == []


# ---------------------------------------------------------------------------
# tool_query_local_token_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_local_token_usage_aggregates_and_groups(monkeypatch):
    entries = [
        {
            "entry_type": "model_call",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_units": 3,
            "created_at": "2026-06-01",
            "run_id": "r1",
            "user_id": "u1",
        },
        {
            "entry_type": "model_call",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_units": 6,
            "created_at": "2026-06-02",
            "run_id": "r2",
            "user_id": "u1",
        },
        # tool_call 应被排除
        {"entry_type": "tool_call", "model": "x", "total_tokens": 999},
    ]

    import app.infrastructure.billing.model_usage as mu

    monkeypatch.setattr(mu, "list_model_usage_entries", lambda **kw: list(entries))
    monkeypatch.setattr(mu, "model_usage_ledger_path", lambda: Path("/tmp/no-such-ledger.json"))
    r = await est.tool_query_local_token_usage({"group_by": "model"}, {})
    assert r["ok"] is True
    summ = r["usage_summary"]
    assert summ["total_calls"] == 2  # tool_call 排除
    assert summ["prompt_tokens"] == 300
    assert summ["completion_tokens"] == 150
    assert summ["total_tokens"] == 450
    assert summ["cost_units"] == 9
    # 分组
    g = r["groups"]["deepseek-chat"]
    assert g["calls"] == 2
    assert g["total_tokens"] == 450
    assert r["group_by"] == "model"
    assert r["ledger_exists"] is False
    assert r["detail_count"] == 2


@pytest.mark.asyncio
async def test_query_local_token_usage_group_none_and_limit_zero(monkeypatch):
    entries = [
        {
            "entry_type": "model_call",
            "provider": "openai",
            "model": "gpt-4o",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost_units": 1,
        }
    ]
    import app.infrastructure.billing.model_usage as mu

    monkeypatch.setattr(mu, "list_model_usage_entries", lambda **kw: list(entries))
    monkeypatch.setattr(mu, "model_usage_ledger_path", lambda: Path("/tmp/x.json"))
    r = await est.tool_query_local_token_usage({"group_by": "none", "limit": 0}, {})
    # group_by none → groups 空
    assert r["groups"] == {}
    # limit=0 → 无明细
    assert r["details"] == []
    assert r["detail_count"] == 0


@pytest.mark.asyncio
async def test_query_local_token_usage_import_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "app.infrastructure.billing.model_usage":
            raise ImportError("no billing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = await est.tool_query_local_token_usage({}, {})
    assert r["ok"] is False and "无法导入 billing" in r["error"]


# ---------------------------------------------------------------------------
# 调度入口 handle_specialized
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_specialized_lists_tools_when_no_tool():
    r = await est.handle_specialized("test-qa-runner", {}, {})
    assert r["ok"] is True
    assert r["handler"] == "specialized"
    assert "run_pytest" in r["available_tools"]
    assert r["employee_id"] == "test-qa-runner"


@pytest.mark.asyncio
async def test_handle_specialized_tool_not_in_allowlist():
    # site-content-editor 不允许 run_pytest
    r = await est.handle_specialized("site-content-editor", {"tool": "run_pytest"}, {})
    assert r["ok"] is False
    assert "不在员工" in r["error"]
    assert "run_pytest" not in r["available_tools"]


@pytest.mark.asyncio
async def test_handle_specialized_params_not_dict():
    r = await est.handle_specialized("git_status_holder", {"tool": "git_status"}, {})
    # 该员工 id 不存在 → tool 不在 allowlist
    assert r["ok"] is False


@pytest.mark.asyncio
async def test_handle_specialized_runs_tool_and_decorates(monkeypatch):
    _install_run_cmd(monkeypatch, {"returncode": 0, "stdout": "", "stderr": "", "ok": True})
    # site-content-editor 允许 git_status
    r = await est.handle_specialized("site-content-editor", {"tool": "git_status"}, {})
    assert r["ok"] is True
    assert r["tool"] == "git_status"
    assert r["employee_id"] == "site-content-editor"
    assert r["handler"] == "specialized"


@pytest.mark.asyncio
async def test_handle_specialized_params_must_be_dict():
    r = await est.handle_specialized(
        "site-content-editor", {"tool": "git_status", "params": ["not", "dict"]}, {}
    )
    assert r["ok"] is False and "params 必须为对象" in r["error"]


@pytest.mark.asyncio
async def test_handle_specialized_tool_execution_exception(monkeypatch):
    async def boom(params, ctx):
        raise RuntimeError("tool crashed")

    monkeypatch.setitem(est.TOOL_REGISTRY, "git_status", boom)
    r = await est.handle_specialized("site-content-editor", {"tool": "git_status"}, {})
    assert r["ok"] is False
    assert "执行异常" in r["error"]


@pytest.mark.asyncio
async def test_handle_specialized_write_gate_blocks(monkeypatch):
    # fhd-core-maintainer 允许 write_file（代码修改工具）→ 走 gate
    async def fake_gate(employee_id, tool_name, params, ctx):
        return {
            "ok": False,
            "reason": "scope violation",
            "pending_approval": True,
            "approval_request_ids": ["a1"],
        }

    monkeypatch.setattr(est, "_check_write_gate", fake_gate)
    r = await est.handle_specialized(
        "fhd-core-maintainer", {"tool": "write_file", "params": {"confirm": True, "path": "x"}}, {}
    )
    assert r["ok"] is False
    assert r["blocked"] is True
    assert r["pending_approval"] is True
    assert r["approval_request_ids"] == ["a1"]


@pytest.mark.asyncio
async def test_handle_specialized_write_gate_passes(monkeypatch, tmp_path):
    async def fake_gate(employee_id, tool_name, params, ctx):
        return {"ok": True}

    monkeypatch.setattr(est, "_check_write_gate", fake_gate)
    r = await est.handle_specialized(
        "fhd-core-maintainer",
        {"tool": "write_file", "params": {"confirm": True, "path": "ok.txt", "content": "data"}},
        {"workspace_root": str(tmp_path)},
    )
    assert r["ok"] is True
    assert (tmp_path / "ok.txt").read_text() == "data"


# ---------------------------------------------------------------------------
# 注册表一致性
# ---------------------------------------------------------------------------


def test_get_employee_tools_known_and_unknown():
    assert est.get_employee_tools("llm-ops-engineer") == [
        "read_llm_env_config",
        "list_configured_providers",
        "test_llm_key_health",
        "query_provider_usage",
        "compare_model_prices",
        "query_local_token_usage",
        "query_cursor_usage",
        "query_codex_usage",
        "query_trae_usage",
    ]
    assert est.get_employee_tools("ghost-employee") == []


def test_list_all_tool_names_sorted_and_complete():
    names = est.list_all_tool_names()
    assert names == sorted(names)
    assert "run_pytest" in names
    assert "query_trae_usage" in names


def test_every_employee_tool_is_registered():
    """每个员工引用的工具名都必须在 TOOL_REGISTRY 中存在（契约一致性）。"""
    registry = set(est.TOOL_REGISTRY)
    for emp_id, tools in est.EMPLOYEE_TOOLS.items():
        for t in tools:
            assert t in registry, f"{emp_id} 引用了未注册工具 {t}"


def test_all_registry_tools_callable():
    for name, fn in est.TOOL_REGISTRY.items():
        assert callable(fn), name


# ---------------------------------------------------------------------------
# cursor / codex / trae usage：真实文件系统 + 子进程/httpx 注入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_cursor_usage_no_sources(monkeypatch, tmp_path):
    # which 返回 None；HOME 指向空目录 → 无 CLI / 无 DB / keychain 失败
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(est.shutil, "which", lambda _: None)

    import subprocess as sp

    def fake_run(*a, **k):
        class _P:
            returncode = 1
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(sp, "run", fake_run)
    r = await est.tool_query_cursor_usage({}, {})
    assert r["ok"] is True
    assert r["sources"] == []
    summ = r["cursor_summary"]
    assert summ["has_cli"] is False
    assert summ["has_api_token"] is False
    assert summ["has_local_db"] is False


@pytest.mark.asyncio
async def test_query_cursor_usage_cli_parses_aggregations(monkeypatch, tmp_path):
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    cli_path = home / "cursor-usage"
    cli_path.write_text("#!/bin/sh")
    monkeypatch.setattr(est.shutil, "which", lambda _: str(cli_path))

    import subprocess as sp

    cli_json = json.dumps(
        {
            "aggregations": [
                {
                    "modelIntent": "gpt-4o",
                    "inputTokens": 1000,
                    "outputTokens": 500,
                    "cacheReadTokens": 200,
                    "cacheWriteTokens": 100,
                    "totalCents": 250.0,
                    "tier": "pro",
                }
            ]
        }
    )

    def fake_run(cmd, **k):
        class _P:
            returncode = 0
            stderr = ""

        p = _P()
        # JSON 调用包含 --json；security keychain 调用返回失败
        if cmd and cmd[0] == "security":
            p.returncode = 1
            p.stdout = ""
        elif "--csv" in cmd:
            p.stdout = "datetime_local,model,input_tokens,output_tokens,cache_read_tokens,value_cents,kind\n2026-06-01,gpt-4o,10,5,2,1.5,chat\n"
        else:
            p.stdout = cli_json
        return p

    monkeypatch.setattr(sp, "run", fake_run)
    r = await est.tool_query_cursor_usage({"days": 7, "detail_limit": 5}, {})
    cli = r["cli_usage"]
    assert cli["total_input_tokens"] == 1000
    assert cli["total_output_tokens"] == 500
    assert cli["total_tokens"] == 1000 + 500 + 200 + 100
    assert cli["total_cost_usd"] == 2.5  # 250 cents
    assert cli["model_count"] == 1
    assert cli["by_model"][0]["model"] == "gpt-4o"
    # 明细 CSV 解析
    assert "recent_events" in cli
    assert cli["recent_events"][0]["model"] == "gpt-4o"
    assert "cursor-usage-cli" in r["sources"]


@pytest.mark.asyncio
async def test_query_cursor_usage_cli_error_branch(monkeypatch, tmp_path):
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    cli_path = home / "cursor-usage"
    cli_path.write_text("#!/bin/sh")
    monkeypatch.setattr(est.shutil, "which", lambda _: str(cli_path))

    import subprocess as sp

    def fake_run(cmd, **k):
        if cmd and cmd[0] == "security":

            class _P:
                returncode = 1
                stdout = ""
                stderr = ""

            return _P()
        raise RuntimeError("cli exploded")

    monkeypatch.setattr(sp, "run", fake_run)
    r = await est.tool_query_cursor_usage({}, {})
    assert "error" in r["cli_usage"]
    assert "cli exploded" in r["cli_usage"]["error"]


@pytest.mark.asyncio
async def test_query_codex_usage_no_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # 无 .codex
    r = await est.tool_query_codex_usage({}, {})
    assert r["ok"] is True
    assert r["sources"] == []
    assert r["codex_summary"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_query_codex_usage_parses_sessions_and_config(monkeypatch, tmp_path):
    codex = tmp_path / ".codex"
    sessions = codex / "archived_sessions"
    sessions.mkdir(parents=True)
    jsonl = sessions / "s1.jsonl"
    jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "model": "gpt-5",
                            "cwd": "/x",
                            "timestamp": "2026-06-20T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 100,
                                    "cached_input_tokens": 10,
                                    "output_tokens": 50,
                                    "reasoning_output_tokens": 5,
                                    "total_tokens": 165,
                                }
                            },
                            "rate_limits": {"primary": {"used_percent": 42}},
                        },
                    }
                ),
                "not-json-line",
            ]
        )
    )
    # config.toml —— reasoning_effort 行在前，model 行在后，规避
    # 源码中 "model_reasoning_effort".startswith("model") 会覆盖 model 的怪异行为。
    (codex / "config.toml").write_text('model_reasoning_effort = "high"\nmodel = "gpt-5"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_codex_usage({"days": 0}, {})
    sess = r["sessions"]
    assert sess["total_sessions"] == 1
    assert sess["total_input_tokens"] == 100
    assert sess["total_tokens"] == 165
    assert sess["by_session"][0]["model"] == "gpt-5"
    assert sess["by_session"][0]["rate_limit_used_percent"] == 42
    assert r["config"]["model"] == "gpt-5"
    assert r["config"]["reasoning_effort"] == "high"
    assert r["codex_summary"]["total_tokens"] == 165
    assert r["codex_summary"]["model"] == "gpt-5"


@pytest.mark.asyncio
async def test_query_codex_usage_date_filter_excludes_old(monkeypatch, tmp_path):
    codex = tmp_path / ".codex"
    sessions = codex / "archived_sessions"
    sessions.mkdir(parents=True)
    (sessions / "old.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"model": "m", "timestamp": "2000-01-01T00:00:00Z"},
                    }
                ),
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {"total_token_usage": {"input_tokens": 1, "total_tokens": 1}},
                            "rate_limits": {},
                        },
                    }
                ),
            ]
        )
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_codex_usage({"days": 30}, {})
    # 2000 年的会话被 30 天过滤排除
    assert r["sessions"]["total_sessions"] == 0


@pytest.mark.asyncio
async def test_query_trae_usage_no_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_trae_usage({}, {})
    assert r["ok"] is True
    assert r["sources"] == []
    assert r["trae_summary"]["chat_turns"] == 0


@pytest.mark.asyncio
async def test_query_trae_usage_jwt_api_non_200(monkeypatch, tmp_path):
    trae_cn = tmp_path / ".trae-cn"
    trae_cn.mkdir()
    (trae_cn / "trae-jwt-token").write_text("jwt-abc")
    monkeypatch.setenv("HOME", str(tmp_path))

    # tool_query_trae_usage 内部 `import httpx as _httpx`，需 patch 真实 httpx.get
    import httpx as real_httpx

    captured: dict[str, Any] = {}

    def fake_get(url, **kw):
        captured["url"] = url
        captured["headers"] = kw.get("headers")
        return _FakeResp(403, {})

    monkeypatch.setattr(real_httpx, "get", fake_get)
    r = await est.tool_query_trae_usage({}, {})
    assert "trae-jwt-token" in r["sources"]
    # 403 → status_code note 分支
    assert r["api_usage"]["status_code"] == 403
    assert captured["headers"]["Authorization"] == "Bearer jwt-abc"
    # api_accessible False（有 status_code）
    assert r["trae_summary"]["api_accessible"] is False


@pytest.mark.asyncio
async def test_query_trae_usage_argv_config(monkeypatch, tmp_path):
    trae_cn = tmp_path / ".trae-cn"
    trae_cn.mkdir()
    (trae_cn / "argv.json").write_text(json.dumps({"locale": "zh-cn"}))
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_trae_usage({}, {})
    assert "argv.json" in r["sources"]
    assert r["config"]["argv"] == {"locale": "zh-cn"}


# ---------------------------------------------------------------------------
# sqlite-backed 数据源（cursor local DB / codex goals / trae state.vscdb）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_cursor_usage_api_token_and_local_db(monkeypatch, tmp_path):
    """keychain token → cursor API + 本地 ai-code-tracking.db sqlite 双数据源。"""
    import sqlite3

    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(est.shutil, "which", lambda _: None)  # 无 CLI

    # keychain 返回 token
    import subprocess as sp

    def fake_run(cmd, **k):
        class _P:
            returncode = 0
            stdout = "tok-123\n"
            stderr = ""

        return _P()

    monkeypatch.setattr(sp, "run", fake_run)

    # cursor API（内部 import httpx as _httpx）
    import httpx as real_httpx

    captured: dict[str, Any] = {}

    def fake_get(url, **k):
        captured["url"] = url
        captured["headers"] = k.get("headers")
        return _FakeResp(200, {"startOfMonth": "2026-06-01", "gpt4": {"numRequests": 12}})

    monkeypatch.setattr(real_httpx, "get", fake_get)

    # 本地 sqlite DB
    db = home / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE ai_code_hashes (model TEXT, timestamp INTEGER)")
    conn.execute("INSERT INTO ai_code_hashes VALUES ('gpt-4o', 9999999999999)")
    conn.execute("INSERT INTO ai_code_hashes VALUES ('gpt-4o', 9999999999999)")
    conn.execute("INSERT INTO ai_code_hashes VALUES (NULL, 9999999999999)")
    conn.execute(
        "CREATE TABLE scored_commits (linesAdded INT, tabLinesAdded INT, composerLinesAdded INT, humanLinesAdded INT)"
    )
    conn.execute("INSERT INTO scored_commits VALUES (100, 30, 20, 50)")
    conn.commit()
    conn.close()

    r = await est.tool_query_cursor_usage({"days": 0}, {})
    # 数据源 2：API token
    assert "cursor-api:auth/usage" in r["sources"]
    assert r["api_usage"]["start_of_month"] == "2026-06-01"
    assert captured["headers"]["Authorization"] == "Bearer tok-123"
    # 数据源 3：本地 DB
    assert any(s.startswith("local-db:") for s in r["sources"])
    ldb = r["local_db"]
    assert ldb["total_ai_generations"] == 3
    # by_model 排序，NULL → (unknown)
    models = {m["model"]: m["count"] for m in ldb["by_model"]}
    assert models["gpt-4o"] == 2
    assert models["(unknown)"] == 1
    # ai_percentage = (tab+composer)/total*100 = (30+20)/100*100 = 50.0
    assert ldb["commits"]["ai_percentage"] == 50.0
    assert r["cursor_summary"]["has_api_token"] is True
    assert r["cursor_summary"]["has_local_db"] is True


@pytest.mark.asyncio
async def test_query_codex_usage_goals_db(monkeypatch, tmp_path):
    """codex goals_1.sqlite → thread_goals 表统计。"""
    import sqlite3

    codex = tmp_path / ".codex"
    codex.mkdir(parents=True)
    db = codex / "goals_1.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE thread_goals (thread_id TEXT, objective TEXT, status TEXT, "
        "token_budget INT, tokens_used INT, time_used_seconds INT, created_at_ms INT)"
    )
    conn.execute(
        "INSERT INTO thread_goals VALUES ('t1', 'obj one', 'completed', 1000, 300, 60, 1700000000000)"
    )
    conn.execute(
        "INSERT INTO thread_goals VALUES ('t2', 'obj two', 'running', 2000, 700, 120, 1700000001000)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_codex_usage({"days": 0}, {})
    assert "goals-sqlite" in r["sources"]
    gdb = r["goals_db"]
    assert gdb["total_threads"] == 2
    assert gdb["total_tokens_used"] == 1000
    assert gdb["total_time_seconds"] == 180
    # by_status 统计
    assert gdb["by_status"]["completed"] == 1
    assert gdb["by_status"]["running"] == 1
    # 无 sessions → summary 回退到 goals tokens
    assert r["codex_summary"]["total_threads"] == 2


@pytest.mark.asyncio
async def test_query_trae_usage_state_vscdb(monkeypatch, tmp_path):
    """trae state.vscdb → ItemTable 提取聊天轮次/模型/用户。"""
    import sqlite3

    monkeypatch.setenv("HOME", str(tmp_path))
    state_db = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Trae CN"
        / "User"
        / "globalStorage"
        / "state.vscdb"
    )
    state_db.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    rows = [
        ("ai.chat.feedback.accumulatedTurns", "57"),
        # current_models 查询 LIKE '%sessionRelation:globalModelMap%'；
        # 故意不含 'ai-chat:sessionRelation' 子串，避免命中 user_id 查询
        ("chat.globalState.sessionRelation:globalModelMap", json.dumps({"chat": "gpt-4o"})),
        ("any.model_list_map.key", json.dumps({"chat": [{"name": "gpt-4o"}, {"name": "claude"}]})),
        ("user42_ai-chat:sessionRelation", "rel"),
    ]
    conn.executemany("INSERT INTO ItemTable VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    r = await est.tool_query_trae_usage({}, {})
    assert "state.vscdb" in r["sources"]
    local = r["local_state"]
    assert local["accumulated_chat_turns"] == 57
    assert local["current_models"] == {"chat": "gpt-4o"}
    assert local["available_models_by_mode"]["chat"] == ["gpt-4o", "claude"]
    assert local["user_id"] == "user42"
    assert r["trae_summary"]["chat_turns"] == 57


@pytest.mark.asyncio
async def test_query_trae_usage_api_success(monkeypatch, tmp_path):
    """trae API 返回 200 → api_usage 为原始 JSON，api_accessible True。"""
    trae_cn = tmp_path / ".trae-cn"
    trae_cn.mkdir()
    (trae_cn / "trae-jwt-token").write_text("jwt-xyz")
    monkeypatch.setenv("HOME", str(tmp_path))

    import httpx as real_httpx

    monkeypatch.setattr(real_httpx, "get", lambda url, **k: _FakeResp(200, {"tokens": 999}))
    r = await est.tool_query_trae_usage({}, {})
    assert r["api_usage"] == {"tokens": 999}
    assert r["trae_summary"]["api_accessible"] is True


@pytest.mark.asyncio
async def test_query_trae_usage_api_exception(monkeypatch, tmp_path):
    """trae API 抛异常 → api_usage error 分支。"""
    trae_cn = tmp_path / ".trae-cn"
    trae_cn.mkdir()
    (trae_cn / "trae-jwt-token").write_text("jwt-xyz")
    monkeypatch.setenv("HOME", str(tmp_path))

    import httpx as real_httpx

    def boom(url, **k):
        raise RuntimeError("net down")

    monkeypatch.setattr(real_httpx, "get", boom)
    r = await est.tool_query_trae_usage({}, {})
    assert "error" in r["api_usage"]
    assert "net down" in r["api_usage"]["error"]


@pytest.mark.asyncio
async def test_query_trae_usage_state_db_exception(monkeypatch, tmp_path):
    """state.vscdb 损坏（非 sqlite）→ local_state error 分支。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    state_db = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Trae CN"
        / "User"
        / "globalStorage"
        / "state.vscdb"
    )
    state_db.parent.mkdir(parents=True)
    state_db.write_text("not a sqlite file")
    r = await est.tool_query_trae_usage({}, {})
    assert "state.vscdb" in r["sources"]
    assert "error" in r["local_state"]


@pytest.mark.asyncio
async def test_query_codex_goals_db_exception(monkeypatch, tmp_path):
    """goals_1.sqlite 损坏 → goals_db error 分支。"""
    codex = tmp_path / ".codex"
    codex.mkdir(parents=True)
    (codex / "goals_1.sqlite").write_text("garbage not sqlite")
    monkeypatch.setenv("HOME", str(tmp_path))
    r = await est.tool_query_codex_usage({"days": 0}, {})
    assert "goals-sqlite" in r["sources"]
    assert "error" in r["goals_db"]


@pytest.mark.asyncio
async def test_query_cursor_cli_nonzero_returncode(monkeypatch, tmp_path):
    """cursor-usage CLI returncode!=0 → 不解析 cli_usage，但 source 已登记。"""
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    cli_path = home / "cursor-usage"
    cli_path.write_text("#!/bin/sh")
    monkeypatch.setattr(est.shutil, "which", lambda _: str(cli_path))

    import subprocess as sp

    def fake_run(cmd, **k):
        class _P:
            returncode = 2  # 非 0
            stdout = ""
            stderr = "cli error"

        return _P()

    monkeypatch.setattr(sp, "run", fake_run)
    r = await est.tool_query_cursor_usage({}, {})
    assert "cursor-usage-cli" in r["sources"]
    # returncode!=0 → cli_usage 保持 None
    assert r["cli_usage"] is None
    assert r["cursor_summary"]["has_cli"] is False


@pytest.mark.asyncio
async def test_read_file_truncation_flag(monkeypatch, tmp_path):
    big = "a" * 60000
    (tmp_path / "big.txt").write_text(big)
    monkeypatch.setattr(est, "_FHD_ROOT", tmp_path)
    r = await est.tool_read_file({"path": "big.txt"}, {})
    assert r["ok"] is True
    assert r["truncated"] is True
    assert len(r["content"]) == 50000


@pytest.mark.asyncio
async def test_query_local_token_usage_group_by_provider(monkeypatch):
    entries = [
        {
            "entry_type": "model_call",
            "provider": "b.ai",
            "model": "m1",
            "total_tokens": 10,
            "prompt_tokens": 6,
            "completion_tokens": 4,
            "cost_units": 1,
        },
        {
            "entry_type": "model_call",
            "provider": "b.ai",
            "model": "m2",
            "total_tokens": 20,
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "cost_units": 2,
        },
        {
            "entry_type": "model_call",
            "provider": "openai",
            "model": "m3",
            "total_tokens": 5,
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "cost_units": 0,
        },
    ]
    import app.infrastructure.billing.model_usage as mu

    monkeypatch.setattr(mu, "list_model_usage_entries", lambda **kw: list(entries))
    monkeypatch.setattr(mu, "model_usage_ledger_path", lambda: Path("/tmp/x.json"))
    r = await est.tool_query_local_token_usage({"group_by": "provider"}, {})
    assert set(r["groups"]) == {"b.ai", "openai"}
    assert r["groups"]["b.ai"]["calls"] == 2
    assert r["groups"]["b.ai"]["total_tokens"] == 30
    assert r["groups"]["openai"]["calls"] == 1
