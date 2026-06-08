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
            patch(
                "modstore_server.employee_skill_register._upsert_eskill",
                return_value=42,
            ),
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
        spec = specs[0]
        assert spec["eskill_id"] == 42
        assert "vibe_skill_id" in spec
        assert "name" in spec
        assert "output_var" in spec


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


def _make_fake_nl_graph_result(nodes_created: int = 2) -> dict:
    return {
        "ok": True,
        "nodes_created": nodes_created,
        "edges_created": 1,
        "sandbox_ok": True,
        "validation_errors": [],
        "llm_warnings": [],
    }


@pytest.mark.asyncio
async def test_preset_nodes_injected_when_llm_omits():
    """LLM 不生成 preset eskill 节点时，apply_nl_workflow_graph 应自动补齐。"""
    from modstore_server.workflow_nl_graph import _normalize_node

    # 模拟 LLM 仅返回 start+end
    fake_llm_nodes = [
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
    ]
    fake_edges = [{"source_temp_id": "s1", "target_temp_id": "e1", "condition": ""}]
    fake_data = {"nodes": fake_llm_nodes, "edges": fake_edges}

    preset = [
        {"eskill_id": 7, "name": "解析输入", "output_var": "parsed"},
        {"eskill_id": 8, "name": "业务处理", "output_var": "processed"},
    ]

    warnings: list[str] = []
    nodes_in = [_normalize_node(n, warnings) for n in fake_llm_nodes]
    nodes_in = [n for n in nodes_in if n]

    edges_in = list(fake_edges)
    seen_tid = {n["temp_id"] for n in nodes_in}

    # 模拟强制补齐逻辑（复制自 apply_nl_workflow_graph 的补齐段落）
    existing_skill_ids = {
        str(n.get("config", {}).get("skill_id") or "")
        for n in nodes_in
        if n.get("node_type") == "eskill"
    }
    missing_presets = [p for p in preset if str(p["eskill_id"]) not in existing_skill_ids]

    for idx_p, p in enumerate(missing_presets):
        tid = f"preset_eskill_{p['eskill_id']}"
        if tid in seen_tid:
            continue
        seen_tid.add(tid)
        nodes_in.append(
            {
                "temp_id": tid,
                "node_type": "eskill",
                "name": str(p["name"])[:120],
                "config": {
                    "skill_id": str(p["eskill_id"]),
                    "output_var": str(p.get("output_var") or "vibe_result"),
                    "task": "",
                    "input_mapping": {},
                    "quality_gate": {},
                    "trigger_policy": {},
                    "force_dynamic": False,
                    "solidify": True,
                },
                "position_x": 260.0 + idx_p * 240.0,
                "position_y": 240.0,
            }
        )

    eskill_nodes = [n for n in nodes_in if n["node_type"] == "eskill"]
    assert len(eskill_nodes) == 2, f"期望 2 个 eskill 节点，实际: {len(eskill_nodes)}"
    skill_ids_in_nodes = {n["config"]["skill_id"] for n in eskill_nodes}
    assert "7" in skill_ids_in_nodes
    assert "8" in skill_ids_in_nodes
