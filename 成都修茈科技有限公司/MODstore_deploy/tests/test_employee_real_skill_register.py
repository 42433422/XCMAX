"""测试 employee_skill_register 与 apply_nl_workflow_graph(preset_eskill_nodes) 的集成。

覆盖三个核心场景：
1. 员工包有 .py → 注册为 ESkill（兜底 A，vibe-coding 不可用时）
2. 注册结果通过 preset_eskill_nodes 注入画布，LLM 漏掉节点时自动补齐
3. 兼容空脚本目录（backend/employees 不存在）→ 返回空列表，旧行为不变
"""

from __future__ import annotations

import json
import tempfile
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(uid: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = uid
    return u


def _make_db(eskill_rows: list | None = None) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.add = MagicMock()
    return db


def _make_pack_dir(tmp: Path, source: str = "def execute(**kwargs):\n    return {}\n") -> Path:
    emp_dir = tmp / "backend" / "employees"
    emp_dir.mkdir(parents=True, exist_ok=True)
    (emp_dir / "main.py").write_text(source, encoding="utf-8")
    (tmp / "manifest.json").write_text(
        json.dumps({"id": "test_pack", "name": "Test Pack"}), encoding="utf-8"
    )
    return tmp


def _make_pack_dir_with_skills(tmp: Path) -> Path:
    pack = _make_pack_dir(tmp)
    manifest = {
        "id": "test_pack",
        "name": "Test Pack",
        "employee": {"id": "test", "label": "测试员工", "capabilities": ["复核结果"]},
        "employee_config_v2": {
            "cognition": {
                "skills": [
                    {"name": "解析输入", "brief": "提取用户 payload 中的关键字段"},
                    {"name": "生成报告", "brief": "根据处理结果生成结构化报告"},
                ]
            },
            "metadata": {
                "suggested_skills": [{"name": "风险检查", "brief": "检查结果中的风险和缺失信息"}]
            },
        },
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return pack


# ---------------------------------------------------------------------------
# 场景 1: 有脚本 → 注册为 ESkill（mock vibe coder，A 注册成功，B 升级跳过）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_with_script_returns_eskill_spec():
    """有脚本 + mock coder，应返回至少 1 个 eskill_spec。"""
    from modstore_server.employee_skill_register import register_employee_pack_as_eskills

    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = _make_pack_dir(Path(tmpdir))

        # mock coder
        mock_coder = MagicMock()
        mock_coder.code_store = MagicMock()
        mock_coder.code_store.has_code_skill.return_value = False
        mock_coder.code_store.save_code_skill = MagicMock()
        # B 升级失败（RuntimeError），应回退到兜底 skill_id
        mock_coder.code.side_effect = RuntimeError("upgrade skipped in test")

        db = _make_db()
        user = _make_user()

        # mock ESkill flush → 给 id
        created_eskill = MagicMock()
        created_eskill.id = 42
        db.add.side_effect = lambda obj: (
            setattr(obj, "id", 42) if hasattr(obj, "eskill_id") or not hasattr(obj, "id") else None
        )

        # mock LLM 拆分返回空（回退单步）
        async def _fake_chat(*args, **kwargs):
            return {"ok": False, "error": "mock"}

        with (
            patch(
                "modstore_server.integrations.vibe_adapter.get_vibe_coder",
                return_value=mock_coder,
            ),
            patch(
                "modstore_server.employee_skill_register.get_vibe_coder",
                return_value=mock_coder,
            ),
            patch(
                "modstore_server.employee_skill_register._llm_split_steps",
                new=AsyncMock(return_value=[]),
            ),
            # _register_script_in_code_store hard-requires the optional vibe_coding
            # package; stub it so the real splitting / spec-assembly logic runs.
            patch(
                "modstore_server.employee_skill_register._register_script_in_code_store"
            ) as mock_register_script,
            patch(
                "modstore_server.employee_skill_register._upsert_eskill",
                side_effect=lambda *a, **kw: 42,
            ) as mock_upsert,
        ):
            specs = await register_employee_pack_as_eskills(
                db,
                user,
                pack_dir=pack_dir,
                brief="测试员工，处理输入并输出结果",
                provider="openai",
                model="gpt-4o",
            )

        assert isinstance(specs, list)
        assert len(specs) >= 2
        # Real side effects (not a tautology on the mocked return value):
        # every produced spec must have driven an _upsert_eskill DB write and a
        # code-store registration.
        assert mock_upsert.call_count == len(specs)
        assert mock_register_script.call_count >= len(specs)
        # _upsert_eskill is always called by keyword with a real vibe_skill_id.
        for call in mock_upsert.call_args_list:
            assert call.kwargs["vibe_skill_id"]
            assert call.kwargs["name"]
        spec = specs[0]
        assert spec["eskill_id"] == 42
        assert spec["vibe_skill_id"]
        assert spec["name"]
        assert spec["output_var"]


# ---------------------------------------------------------------------------
# 场景 2: LLM 拆分为 3 步 → 多步注册
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_multi_step_split():
    """LLM 成功返回 3 步时，应注册 3 个 ESkill。"""
    from modstore_server.employee_skill_register import register_employee_pack_as_eskills

    split_steps = [
        {
            "name": "解析输入",
            "sub_brief": "解析 kwargs 并归一化",
            "input_keys": ["data"],
            "output_var": "parsed",
            "domain": "通用",
        },
        {
            "name": "业务处理",
            "sub_brief": "执行核心业务逻辑",
            "input_keys": ["parsed"],
            "output_var": "processed",
            "domain": "通用",
        },
        {
            "name": "格式化输出",
            "sub_brief": "把结果格式化为 JSON",
            "input_keys": ["processed"],
            "output_var": "output",
            "domain": "通用",
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = _make_pack_dir(Path(tmpdir))

        mock_coder = MagicMock()
        mock_coder.code_store = MagicMock()
        mock_coder.code_store.has_code_skill.return_value = False
        mock_coder.code_store.save_code_skill = MagicMock()
        mock_coder.code.side_effect = RuntimeError("no LLM in test")

        upsert_id_seq = iter(range(10, 20))

        with (
            patch(
                "modstore_server.employee_skill_register.get_vibe_coder",
                return_value=mock_coder,
            ),
            patch(
                "modstore_server.employee_skill_register._llm_split_steps",
                new=AsyncMock(return_value=split_steps),
            ),
            patch("modstore_server.employee_skill_register._register_script_in_code_store"),
            patch(
                "modstore_server.employee_skill_register._upsert_eskill",
                side_effect=lambda *a, **kw: next(upsert_id_seq),
            ),
        ):
            specs = await register_employee_pack_as_eskills(
                _make_db(),
                _make_user(),
                pack_dir=pack_dir,
                brief="处理输入并生成报告",
                provider="openai",
                model="gpt-4o",
            )

        assert len(specs) == 3
        output_vars = [s["output_var"] for s in specs]
        assert "parsed" in output_vars
        assert "processed" in output_vars
        assert "output" in output_vars


@pytest.mark.asyncio
async def test_register_manifest_skills_when_llm_split_fails():
    """LLM 拆分失败时，仍应从 manifest 的 skills/suggested_skills 拆出多个 ESkill。"""
    from modstore_server.employee_skill_register import register_employee_pack_as_eskills

    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = _make_pack_dir_with_skills(Path(tmpdir))

        mock_coder = MagicMock()
        mock_coder.code_store = MagicMock()
        mock_coder.code_store.has_code_skill.return_value = False
        mock_coder.code_store.save_code_skill = MagicMock()
        mock_coder.code.side_effect = RuntimeError("no LLM in test")

        upsert_id_seq = iter(range(30, 40))

        with (
            patch(
                "modstore_server.employee_skill_register.get_vibe_coder",
                return_value=mock_coder,
            ),
            patch(
                "modstore_server.employee_skill_register._llm_split_steps",
                new=AsyncMock(return_value=[]),
            ),
            patch("modstore_server.employee_skill_register._register_script_in_code_store"),
            patch(
                "modstore_server.employee_skill_register._upsert_eskill",
                side_effect=lambda *a, **kw: next(upsert_id_seq),
            ),
        ):
            specs = await register_employee_pack_as_eskills(
                _make_db(),
                _make_user(),
                pack_dir=pack_dir,
                brief="处理输入并生成报告",
                provider="openai",
                model="gpt-4o",
            )

    assert len(specs) >= 3
    names = " ".join(s["name"] for s in specs)
    assert "解析输入" in names
    assert "生成报告" in names
    assert "风险检查" in names


# ---------------------------------------------------------------------------
# 场景 3: 空脚本目录 → 返回空列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_no_script_returns_empty():
    """无 backend/employees/*.py 时，应返回空列表（不报错）。"""
    from modstore_server.employee_skill_register import register_employee_pack_as_eskills

    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = Path(tmpdir)
        # 不创建 backend/employees 目录

        specs = await register_employee_pack_as_eskills(
            _make_db(),
            _make_user(),
            pack_dir=pack_dir,
            brief="无脚本员工",
            provider="openai",
            model="gpt-4o",
        )

        assert specs == []


# ---------------------------------------------------------------------------
# 场景 4: vibe-coding 未安装 → 返回空列表（不崩溃）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_vibe_unavailable_returns_empty():
    """get_vibe_coder 抛 VibeIntegrationError → 返回空列表。"""
    from modstore_server.employee_skill_register import register_employee_pack_as_eskills

    with tempfile.TemporaryDirectory() as tmpdir:
        pack_dir = _make_pack_dir(Path(tmpdir))

        from modstore_server.integrations.vibe_adapter import VibeIntegrationError

        with patch(
            "modstore_server.employee_skill_register.get_vibe_coder",
            side_effect=VibeIntegrationError("vibe-coding not installed"),
        ):
            specs = await register_employee_pack_as_eskills(
                _make_db(),
                _make_user(),
                pack_dir=pack_dir,
                brief="测试",
                provider="openai",
                model="gpt-4o",
            )

        assert specs == []


# ---------------------------------------------------------------------------
# 场景 5: preset_eskill_nodes 注入 apply_nl_workflow_graph —— 验证强制补齐
# ---------------------------------------------------------------------------


def _make_mock_db_with_workflow() -> MagicMock:
    """MagicMock Session: Workflow 查询返回伪行，flush 给新增行赋递增 id。"""
    wf = MagicMock()
    wf.id = 1
    wf.name = "测试工作流"
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = wf
    state: dict[str, Any] = {"next_id": 1, "last": None}

    def _add(obj: Any) -> None:
        state["last"] = obj

    def _flush() -> None:
        last = state["last"]
        if last is not None and getattr(last, "id", None) is None:
            last.id = state["next_id"]
            state["next_id"] += 1

    db.add.side_effect = _add
    db.flush.side_effect = _flush
    return db


@pytest.mark.asyncio
async def test_preset_nodes_injected_when_llm_omits():
    """LLM 不生成 preset eskill 节点时，apply_nl_workflow_graph 应真正自动补齐。

    调用真实的 apply_nl_workflow_graph（仅 mock LLM 调用 / 沙箱 / DB 会话三个外部
    边界），让 LLM 只返回 start+end，断言生产代码自身把漏掉的预置 ESkill 节点补回，
    并以正确的 skill_id 落库、串进 start→eskill→end 链。
    """
    import json as _json

    import modstore_server.workflow_nl_graph as g

    db = _make_mock_db_with_workflow()
    user = _make_user()

    # LLM 仅返回 start+end，故意漏掉预置的 eskill 节点。
    llm_payload = {
        "workflow": {
            "nodes": [
                {
                    "temp_id": "s1",
                    "node_type": "start",
                    "name": "开始",
                    "config": {},
                    "position_x": 0,
                    "position_y": 0,
                },
                {
                    "temp_id": "e1",
                    "node_type": "end",
                    "name": "结束",
                    "config": {},
                    "position_x": 440,
                    "position_y": 0,
                },
            ],
            "edges": [{"source_temp_id": "s1", "target_temp_id": "e1", "condition": ""}],
        }
    }

    preset = [{"eskill_id": 7, "name": "解析输入", "output_var": "parsed"}]

    with (
        patch(
            "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
            return_value=("openai", "gpt-4o", None),
        ),
        patch.object(
            g,
            "chat_dispatch_via_session",
            new=AsyncMock(return_value={"ok": True, "content": _json.dumps(llm_payload)}),
        ),
        patch.object(g, "_eskill_catalog_lines", return_value=""),
        patch.object(g, "_create_generated_skills", return_value={}),
        patch.object(g, "run_workflow_sandbox", return_value={"ok": True, "errors": []}),
    ):
        result = await g.apply_nl_workflow_graph(
            db,
            user,
            workflow_id=1,
            brief="串接预置 ESkill",
            provider="openai",
            model="gpt-4o",
            preset_eskill_nodes=preset,
        )

    assert result["ok"] is True
    # start + end + 自动补齐的 1 个 eskill = 3 个节点。
    assert result["nodes_created"] == 3
    assert any("自动插入" in w for w in result["llm_warnings"])

    # 检查真正落库的节点：必须含一个 skill_id=7、名为「解析输入」的 eskill 行。
    persisted_nodes = [
        c.args[0] for c in db.add.call_args_list if getattr(c.args[0], "node_type", None) is not None
    ]
    node_types = [n.node_type for n in persisted_nodes]
    assert node_types.count("eskill") == 1
    assert "start" in node_types and "end" in node_types

    eskill_row = next(n for n in persisted_nodes if n.node_type == "eskill")
    assert eskill_row.name == "解析输入"
    eskill_cfg = _json.loads(eskill_row.config)
    assert eskill_cfg["skill_id"] == "7"
    assert eskill_cfg["output_var"] == "parsed"
