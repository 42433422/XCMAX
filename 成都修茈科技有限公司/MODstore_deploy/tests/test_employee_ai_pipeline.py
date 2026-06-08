"""单元测试 & 集成测试：employee_ai_pipeline 6 阶段流水线。

每个 stage 单测使用 StubLlmClient（预设回复 FIFO 队列）；
orchestrator 集成测试覆盖三条路径：
  1. 工作流 LLM 匹配（score >= threshold）
  2. 工作流兜底生成（score < threshold，调 generate_fallback）
  3. Stage 1 失败中止（返回 None）
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from modstore_server.employee_ai_pipeline import (
    EmployeeConfigV2,
    Intent,
    PricingHint,
    SuggestedSkill,
    WorkflowChoice,
    refine_system_prompt,
    run_pipeline,
    stage_assemble,
    stage_design_v2,
    stage_parse_intent,
    stage_resolve_workflow,
    stage_suggest_pricing,
    stage_suggest_skills,
)
from modstore_server.script_agent.llm_client import StubLlmClient

# ── fixtures ──────────────────────────────────────────────────────────────────

INTENT_JSON = json.dumps(
    {
        "id": "refund-assistant",
        "name": "退款客服助手",
        "role": "退款流程处理",
        "scenario": "用户提交退款申请后自动核查订单并输出处理意见",
        "industry": "电商",
        "complexity": "medium",
    }
)

RANK_JSON_MATCH = json.dumps({"best_index": 0, "score": 0.82, "reason": "完全匹配退款场景"})
RANK_JSON_NO_MATCH = json.dumps({"best_index": -1, "score": 0.1, "reason": "无匹配"})

V2_JSON = json.dumps(
    {
        "perception": {"type": "document"},
        "memory": {"type": "long_term", "knowledge_base": "退款政策知识库"},
        "cognition": {
            "agent": {
                "system_prompt": (
                    "你是退款客服助手，专门负责处理用户退款申请。"
                    "工作步骤：1. 核查订单有效性 2. 判断是否符合退款条件 3. 输出处理意见。"
                    "禁止：不得承诺未经核实的退款金额；不得透露内部系统数据。"
                    "输出格式：结构化 JSON，包含 decision/amount/reason 三个字段。"
                ),
                "model": {
                    "provider": "deepseek",
                    "model_name": "deepseek-chat",
                    "temperature": 0.2,
                },
            }
        },
        "actions": {"handlers": ["text_output", "notify"]},
    }
)

SKILLS_JSON = json.dumps(
    [
        {"name": "订单查询", "brief": "根据订单号查询状态与详情"},
        {"name": "退款计算", "brief": "按规则计算可退金额"},
    ]
)

PRICING_JSON = json.dumps(
    {
        "tier": "standard",
        "cny": 29,
        "period": "month",
        "reasoning": "中等复杂度，含长期记忆与通知功能，标准档定价合理",
    }
)

SAMPLE_INTENT = Intent(
    id="refund-assistant",
    name="退款客服助手",
    role="退款流程处理",
    scenario="用户提交退款申请后自动核查订单并输出处理意见",
    industry="电商",
    complexity="medium",
)

SAMPLE_WF_CHOICE = WorkflowChoice(
    workflow_id=42, workflow_name="退款工作流", match_score=0.82, generated=False
)

SAMPLE_V2 = EmployeeConfigV2(
    perception={"type": "document"},
    memory={"type": "long_term", "knowledge_base": "退款政策知识库"},
    cognition={
        "agent": {
            "system_prompt": "你是退款客服助手，专门负责退款流程处理。" * 5,
            "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
        }
    },
    actions={"handlers": ["text_output", "notify"]},
)

SAMPLE_SKILLS = [
    SuggestedSkill(name="订单查询", brief="查询订单状态"),
    SuggestedSkill(name="退款计算", brief="计算可退金额"),
]

SAMPLE_PRICING = PricingHint(tier="standard", cny=29.0, period="month", reasoning="标准档")


# ── stage unit tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage_parse_intent_ok():
    llm = StubLlmClient([INTENT_JSON])
    intent, err = await stage_parse_intent("我要一个能处理退款的客服助手", llm)
    assert err == ""
    assert intent is not None
    assert intent.id == "refund-assistant"
    assert intent.name == "退款客服助手"
    assert intent.complexity == "medium"


@pytest.mark.asyncio
async def test_stage_parse_intent_bad_json():
    llm = StubLlmClient(["not-json!!"])
    intent, err = await stage_parse_intent("brief", llm)
    assert intent is None
    assert "JSON" in err


@pytest.mark.asyncio
async def test_stage_parse_intent_id_sanitized():
    bad_id_json = json.dumps(
        {
            "id": "Hello World!!",
            "name": "测试",
            "role": "role",
            "scenario": "sc",
            "industry": "通用",
            "complexity": "low",
        }
    )
    llm = StubLlmClient([bad_id_json])
    intent, err = await stage_parse_intent("brief", llm)
    assert err == ""
    assert intent is not None
    assert " " not in intent.id
    assert "!" not in intent.id


@pytest.mark.asyncio
async def test_stage_resolve_workflow_match():
    llm = StubLlmClient([RANK_JSON_MATCH])
    wfs = [{"id": 42, "name": "退款工作流", "description": "处理用户退款"}]
    choice, err = await stage_resolve_workflow(SAMPLE_INTENT, wfs, llm, score_threshold=0.55)
    assert err == ""
    assert choice is not None
    assert choice.workflow_id == 42
    assert choice.generated is False
    assert choice.match_score == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_stage_resolve_workflow_no_match_with_fallback():
    llm = StubLlmClient([RANK_JSON_NO_MATCH])
    wfs = [{"id": 1, "name": "完全不相关流程", "description": ""}]
    fallback_called = []

    async def fake_fallback():
        fallback_called.append(True)
        return {"ok": True, "workflow_id": 99, "name": "生成的工作流"}

    choice, err = await stage_resolve_workflow(
        SAMPLE_INTENT, wfs, llm, generate_fallback=fake_fallback, score_threshold=0.55
    )
    assert err == ""
    assert choice is not None
    assert choice.workflow_id == 99
    assert choice.generated is True
    assert fallback_called


@pytest.mark.asyncio
async def test_stage_resolve_workflow_empty_list_no_fallback():
    llm = StubLlmClient([])
    choice, err = await stage_resolve_workflow(SAMPLE_INTENT, [], llm)
    assert err == ""
    assert choice is not None
    assert choice.workflow_id is None
    assert choice.generated is False


@pytest.mark.asyncio
async def test_stage_resolve_workflow_fallback_fails():
    llm = StubLlmClient([RANK_JSON_NO_MATCH])
    wfs = [{"id": 1, "name": "x", "description": ""}]

    async def fail_fallback():
        return {"ok": False, "error": "NL 生图失败"}

    choice, err = await stage_resolve_workflow(
        SAMPLE_INTENT, wfs, llm, generate_fallback=fail_fallback, score_threshold=0.55
    )
    assert choice is None
    assert "NL 生图失败" in err


@pytest.mark.asyncio
async def test_stage_design_v2_ok():
    llm = StubLlmClient([V2_JSON])
    v2, err = await stage_design_v2(
        SAMPLE_INTENT, SAMPLE_WF_CHOICE, llm, suggested_skills=SAMPLE_SKILLS
    )
    assert err == ""
    assert v2 is not None
    assert v2.perception["type"] == "document"
    assert v2.memory["type"] == "long_term"
    assert "system_prompt" in v2.cognition["agent"]
    assert "text_output" in v2.actions["handlers"]
    prompt = v2.cognition["agent"]["system_prompt"]
    assert "退款工作流" in prompt
    assert "订单查询" in prompt
    assert "不得编造" in prompt


@pytest.mark.asyncio
async def test_stage_design_v2_missing_prompt_gets_default():
    no_prompt = json.dumps(
        {
            "perception": {"type": "text"},
            "memory": {"type": "session"},
            "cognition": {
                "agent": {
                    "system_prompt": "",
                    "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
                }
            },
            "actions": {"handlers": ["echo"]},
        }
    )
    llm = StubLlmClient([no_prompt])
    v2, err = await stage_design_v2(SAMPLE_INTENT, None, llm)
    assert err == ""
    assert v2 is not None
    assert v2.cognition["agent"]["system_prompt"]  # filled by default
    assert v2.actions["handlers"] == ["llm_md", "echo"]


@pytest.mark.asyncio
async def test_stage_design_v2_rejects_api_template_prompt():
    templated = json.dumps(
        {
            "perception": {"type": "text"},
            "memory": {"type": "session"},
            "cognition": {
                "agent": {
                    "system_prompt": "## 用途\n处理退款\n## 输入\n订单\n## 输出\n结果\n## 示例\n示例",
                    "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
                }
            },
            "actions": {"handlers": ["echo"]},
        }
    )
    llm = StubLlmClient([templated])
    v2, err = await stage_design_v2(
        SAMPLE_INTENT, SAMPLE_WF_CHOICE, llm, suggested_skills=SAMPLE_SKILLS
    )
    assert err == ""
    assert v2 is not None
    prompt = v2.cognition["agent"]["system_prompt"]
    assert "## 用途" not in prompt
    assert "退款工作流" in prompt
    assert "订单查询" in prompt
    assert "不得编造" in prompt
    assert v2.actions["handlers"] == ["llm_md", "echo"]


@pytest.mark.asyncio
async def test_stage_suggest_skills_ok():
    llm = StubLlmClient([SKILLS_JSON])
    skills, err = await stage_suggest_skills(SAMPLE_INTENT, llm)
    assert err == ""
    assert len(skills) == 2
    assert skills[0].name == "订单查询"
    assert skills[0].unverified is True


@pytest.mark.asyncio
async def test_stage_suggest_skills_not_array():
    llm = StubLlmClient(['{"key": "value"}'])
    skills, err = await stage_suggest_skills(SAMPLE_INTENT, llm)
    assert skills == []
    assert "数组" in err


@pytest.mark.asyncio
async def test_stage_suggest_pricing_ok():
    llm = StubLlmClient([PRICING_JSON])
    pricing, err = await stage_suggest_pricing(SAMPLE_INTENT, SAMPLE_V2, SAMPLE_SKILLS, llm)
    assert err == ""
    assert pricing is not None
    assert pricing.tier == "standard"
    assert pricing.cny == pytest.approx(29.0)
    assert pricing.period == "month"


@pytest.mark.asyncio
async def test_stage_assemble_produces_valid_manifest():
    manifest, errs = stage_assemble(
        SAMPLE_INTENT, SAMPLE_WF_CHOICE, SAMPLE_V2, SAMPLE_SKILLS, SAMPLE_PRICING
    )
    assert manifest is not None, f"assemble returned None: {errs}"
    assert manifest["id"] == "refund-assistant"
    assert manifest["artifact"] == "employee_pack"
    assert manifest["employee"]["id"] == "refund-assistant"
    assert manifest["workflow_employees"][0]["id"] == "refund-assistant"
    assert manifest["workflow_employees"][0]["api_base_path"] == "employees/refund-assistant"
    v2 = manifest["employee_config_v2"]
    assert v2["perception"]["type"] == "document"
    assert v2["actions"]["handlers"]
    assert v2["cognition"]["skills"]
    meta = v2["metadata"]
    assert any(s["name"] == "订单查询" for s in meta["suggested_skills"])
    assert meta["suggested_pricing"]["tier"] == "standard"
    assert manifest["employee"]["capabilities"]
    assert manifest["workflow_employees"][0].get("workflow_id") == 42
    assert v2["collaboration"]["workflow"]["name"] == "退款工作流"


@pytest.mark.asyncio
async def test_stage_assemble_no_workflow():
    manifest, errs = stage_assemble(SAMPLE_INTENT, None, SAMPLE_V2, [], None)
    assert manifest is not None
    assert "workflow_employees" in manifest
    assert manifest["employee"]["capabilities"]
    v2 = manifest["employee_config_v2"]
    assert v2["actions"]["handlers"]
    assert v2["cognition"]["skills"]
    assert v2["collaboration"]["workflow"]["name"]


def test_normalize_editor_manifest_fills_runtime_required_fields():
    from modstore_server.employee_ai_scaffold import normalize_editor_manifest_for_registry

    sparse = {
        "identity": {
            "id": "seo-file-maintainer",
            "name": "SEO站点地图维护员",
            "description": "维护 sitemap、robots 和百度推送配置",
        },
        "cognition": {"agent": {"system_prompt": "根据 SEO 维护任务生成结构化执行方案。"}},
        "collaboration": {"workflow": {"workflow_id": 2, "name": ""}},
        "metadata": {"created_by": "test"},
    }
    manifest, errs = normalize_editor_manifest_for_registry(sparse, "seo-file-maintainer")
    assert manifest is not None
    assert not errs
    assert manifest["employee"]["id"] == "seo-file-maintainer"
    assert manifest["workflow_employees"][0]["id"] == "seo-file-maintainer"
    assert manifest["workflow_employees"][0]["api_base_path"] == "employees/seo-file-maintainer"
    assert manifest["employee"]["capabilities"] == [
        "seo.sitemap",
        "seo.robots",
        "seo.baidu_push",
        "seo.verification_files",
    ]
    v2 = manifest["employee_config_v2"]
    assert v2["actions"]["handlers"] == ["llm_md", "echo"]
    assert v2["actions"]["vibe_edit_ready"]["focus_paths"] == [
        "sitemap.xml",
        "sitemap_index.xml",
        "robots.txt",
        "baidu_urls.txt",
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]
    assert [s["name"] for s in v2["cognition"]["skills"]] == [
        "seo.sitemap",
        "seo.robots",
        "seo.baidu_push",
        "seo.verification_files",
    ]
    sitemap_skill = v2["cognition"]["skills"][0]
    assert sitemap_skill["skill_id"] == "skill-seo-sitemap"
    assert sitemap_skill["domain"] == "seo-static-files"
    assert sitemap_skill["static_phase"]["focus_paths"] == ["sitemap.xml", "sitemap_index.xml"]
    assert sitemap_skill["dynamic_phase"]["budget"]["max_steps"] == 5
    assert sitemap_skill["solidify"]["acceptance"]
    assert sitemap_skill["metrics"]["static_success_rate_target"] == ">=95%"
    agent = v2["cognition"]["agent"]
    assert agent["model"]["temperature"] <= 0.3
    assert agent["few_shot_examples"]
    assert "BingSiteAuth.xml" in agent["system_prompt"]
    assert "baidu_verify_*.html" in agent["system_prompt"]
    assert "xml.etree.ElementTree" in agent["system_prompt"]
    assert "只能输出可审阅的 Markdown 方案、文件片段和 unified diff" in agent["system_prompt"]
    assert v2["metadata"]["recommended_filename"] == "seo-file-maintainer.xcemp"
    assert "workflow_id/script_workflow_id" in v2["metadata"]["workflow_runtime_check"]
    assert v2["collaboration"]["workflow"]["name"] == "SEO站点地图维护员"


def test_seo_employee_pack_zip_contains_complete_runnable_manifest():
    from modstore_server.employee_ai_scaffold import (
        build_employee_pack_zip,
        normalize_editor_manifest_for_registry,
    )

    sparse = {
        "identity": {
            "id": "seo-static-file-maintainer",
            "name": "SEO站点地图维护员",
            "description": "检查并维护 sitemap、robots 与百度推送配置，输出修复建议",
        },
        "cognition": {
            "agent": {"system_prompt": "根据 SEO 维护任务生成可执行检查方案，不编造文件状态。"}
        },
        "collaboration": {"workflow": {"workflow_id": 2, "name": ""}},
        "employee": {
            "id": "seo-static-file-maintainer",
            "label": "SEO站点地图维护员",
            "capabilities": [],
        },
        "workflow_employees": [
            {"id": "seo_maintainer", "api_base_path": "employees/seo_maintainer"}
        ],
    }
    manifest, errs = normalize_editor_manifest_for_registry(sparse, "seo-static-file-maintainer")
    assert not errs
    raw = build_employee_pack_zip("seo-static-file-maintainer", manifest)

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        packed = json.loads(zf.read("seo-static-file-maintainer/manifest.json").decode("utf-8"))
        employee_py = zf.read(
            "seo-static-file-maintainer/backend/employees/seo_static_file_maintainer.py"
        ).decode("utf-8")

    v2 = packed["employee_config_v2"]
    assert packed["id"] == "seo-static-file-maintainer"
    assert packed["employee"]["id"] == "seo-static-file-maintainer"
    assert packed["workflow_employees"][0]["id"] == "seo-static-file-maintainer"
    assert (
        packed["workflow_employees"][0]["api_base_path"] == "employees/seo-static-file-maintainer"
    )
    assert "SYSTEM_PROMPT =" in employee_py
    assert packed["employee"]["capabilities"] == [
        "seo.sitemap",
        "seo.robots",
        "seo.baidu_push",
        "seo.verification_files",
    ]
    assert v2["actions"]["handlers"] == ["llm_md", "echo"]
    assert v2["actions"]["vibe_edit_ready"]["focus_paths"] == [
        "sitemap.xml",
        "sitemap_index.xml",
        "robots.txt",
        "baidu_urls.txt",
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]
    assert len(v2["cognition"]["skills"]) >= 4
    verification_skill = next(
        s for s in v2["cognition"]["skills"] if s["name"] == "seo.verification_files"
    )
    assert verification_skill["skill_id"] == "skill-seo-verification-files"
    assert verification_skill["static_phase"]["focus_paths"] == [
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]
    assert verification_skill["trigger_rules"]
    assert verification_skill["dynamic_phase"]["allowed_patch_scope"] == [
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]
    assert verification_skill["solidify"]["actions"]
    agent = v2["cognition"]["agent"]
    assert agent["model"]["temperature"] <= 0.3
    assert agent["few_shot_examples"]
    assert "BingSiteAuth.xml" in agent["system_prompt"]
    assert "baidu_verify_*.html" in agent["system_prompt"]
    assert "xml.etree.ElementTree" in agent["system_prompt"]
    assert "只能输出可审阅的 Markdown 方案、文件片段和 unified diff" in agent["system_prompt"]
    assert v2["metadata"]["recommended_filename"] == "seo-static-file-maintainer.xcemp"
    assert "workflow_id/script_workflow_id" in v2["metadata"]["workflow_runtime_check"]
    assert v2["collaboration"]["workflow"]["name"] == "SEO站点地图维护员"
    assert "offline plan" in employee_py
    assert "ctx.call_llm unavailable" in employee_py


def test_normalize_editor_manifest_overrides_stale_requirement_summary_id():
    from modstore_server.employee_ai_scaffold import normalize_editor_manifest_for_registry

    sparse = {
        "id": "requirement-summary-assistant",
        "identity": {
            "id": "requirement-summary-assistant",
            "name": "SEO站点地图维护员",
            "description": "维护 sitemap.xml、robots.txt、baidu_urls.txt",
        },
        "employee": {
            "id": "requirement-summary-assistant",
            "label": "SEO站点地图维护员",
            "capabilities": [],
        },
        "workflow_employees": [
            {
                "id": "requirement-summary-assistant",
                "api_base_path": "employees/requirement-summary-assistant",
            }
        ],
        "cognition": {
            "agent": {
                "system_prompt": "你是 SEO 站点地图维护员，负责维护 sitemap.xml、robots.txt 与 baidu_urls.txt。"
            }
        },
    }

    manifest, errs = normalize_editor_manifest_for_registry(sparse, "seo-file-maintainer")

    assert not errs
    assert manifest["id"] == "seo-file-maintainer"
    assert manifest["identity"]["id"] == "seo-file-maintainer"
    assert manifest["employee"]["id"] == "seo-file-maintainer"
    assert manifest["workflow_employees"][0]["id"] == "seo-file-maintainer"
    assert manifest["workflow_employees"][0]["api_base_path"] == "employees/seo-file-maintainer"


def test_catalog_alignment_rejects_mismatched_employee_pack_id(tmp_path):
    from modstore_server.catalog_store import package_manifest_alignment_errors
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip

    inner = {
        "id": "requirement-summary-assistant",
        "name": "需求摘要助手",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {
            "id": "requirement-summary-assistant",
            "label": "需求摘要助手",
            "capabilities": [],
        },
    }
    path = tmp_path / "seo-file-maintainer.xcemp"
    path.write_bytes(build_employee_pack_zip("requirement-summary-assistant", inner))

    errors = package_manifest_alignment_errors(
        {
            "id": "seo-file-maintainer",
            "name": "SEO站点地图维护员",
            "version": "1.0.0",
            "artifact": "employee_pack",
        },
        path,
    )

    assert errors
    assert any("manifest.id=requirement-summary-assistant" in e for e in errors)


def test_catalog_alignment_accepts_registry_normalized_stale_employee_ids(tmp_path):
    from modstore_server.catalog_store import package_manifest_alignment_errors
    from modstore_server.employee_ai_scaffold import (
        build_employee_pack_zip,
        normalize_editor_manifest_for_registry,
    )

    stale = {
        "id": "seo-file-maintainer",
        "name": "SEO站点地图维护员",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {"id": "seo-admin", "label": "SEO管理员", "capabilities": []},
        "workflow_employees": [{"id": "seo-admin", "api_base_path": "employees/seo-admin"}],
    }
    manifest, errs = normalize_editor_manifest_for_registry(stale, "seo-file-maintainer")
    assert not errs
    path = tmp_path / "seo-file-maintainer.xcemp"
    path.write_bytes(build_employee_pack_zip("seo-file-maintainer", manifest))

    errors = package_manifest_alignment_errors(
        {
            "id": "seo-file-maintainer",
            "name": "SEO站点地图维护员",
            "version": "1.0.0",
            "artifact": "employee_pack",
        },
        path,
    )

    assert errors == []


def test_seo_vibe_edit_focus_paths_match_asset_scope_when_enabled():
    from modstore_server.employee_ai_scaffold import normalize_editor_manifest_for_registry

    sparse = {
        "identity": {
            "id": "seo-static-file-maintainer",
            "name": "SEO静态文件维护员",
            "description": "自动维护 sitemap、robots、Bing 与百度验证文件",
        },
        "actions": {
            "handlers": ["llm_md", "vibe_edit"],
            "vibe_edit": {"focus_paths": ["robots.txt"]},
        },
        "cognition": {"agent": {"system_prompt": "根据 SEO 维护任务生成可执行检查方案。"}},
    }
    manifest, errs = normalize_editor_manifest_for_registry(sparse, "seo-static-file-maintainer")
    assert not errs
    v2 = manifest["employee_config_v2"]
    assert "vibe_edit" in v2["actions"]["handlers"]
    assert v2["actions"]["vibe_edit"]["focus_paths"] == [
        "robots.txt",
        "sitemap.xml",
        "sitemap_index.xml",
        "baidu_urls.txt",
        "BingSiteAuth.xml",
        "baidu_verify_*.html",
    ]
    assert "xml.etree.ElementTree" in v2["cognition"]["agent"]["system_prompt"]
    assert "自动写入文件" in v2["cognition"]["agent"]["system_prompt"]


def test_workflow_reference_report_marks_missing_ids():
    from modstore_server.workbench_api import _employee_pack_workflow_reference_report

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class _Db:
        def query(self, *_args):
            return _Query()

    user = type("UserStub", (), {"id": 7})()
    manifest = {
        "workflow_employees": [{"id": "seo", "workflow_id": 3}],
        "employee_config_v2": {
            "collaboration": {
                "workflow": {"workflow_id": 3},
                "script_workflows": [{"script_workflow_id": 4}],
            }
        },
    }
    report = _employee_pack_workflow_reference_report(_Db(), user, manifest)
    assert report["packaging"] == "manifest_runtime_only"
    assert report["workflow_ids"] == [3]
    assert report["script_workflow_ids"] == [4]
    assert report["missing_workflow_ids"] == [3]
    assert report["missing_script_workflow_ids"] == [4]
    assert report["ok"] is False
    assert any("不会内嵌" in w for w in report["warnings"])


@pytest.mark.asyncio
async def test_refine_system_prompt_ok():
    result_json = json.dumps(
        {
            "improved_prompt": "你是专业退款客服AI助手，负责处理用户退款申请...",
            "diff_explanation": "增加了具体工作步骤和禁忌规则",
        }
    )
    llm = StubLlmClient([result_json])
    result, err = await refine_system_prompt(
        current_prompt="你是客服助手",
        instruction="增加退款处理的具体步骤",
        role_context="退款场景",
        llm=llm,
    )
    assert err == ""
    assert result is not None
    assert result["improved_prompt"]
    assert result["diff_explanation"]


# ── orchestrator integration tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_workflow_match():
    """Path 1: eligible workflow found with high score."""
    llm = StubLlmClient([INTENT_JSON, RANK_JSON_MATCH, SKILLS_JSON, V2_JSON, PRICING_JSON])
    events: list = []

    async def on_event(ev):
        events.append(ev)

    manifest = await run_pipeline(
        "我要一个能处理退款的客服助手",
        llm=llm,
        on_event=on_event,
        eligible_workflows=[{"id": 42, "name": "退款工作流", "description": "处理退款"}],
    )
    assert manifest is not None
    assert manifest["id"] == "refund-assistant"

    stage_events = {
        e["stage"]: e["event"] for e in events if e.get("event") in ("stage_done", "stage_error")
    }
    assert stage_events.get("parse_intent") == "stage_done"
    assert stage_events.get("resolve_workflow") == "stage_done"
    assert stage_events.get("design_v2") == "stage_done"
    assert stage_events.get("assemble") == "stage_done"
    assert any(e["event"] == "pipeline_done" for e in events)


@pytest.mark.asyncio
async def test_pipeline_workflow_fallback_generation():
    """Path 2: no eligible workflows → fallback generator called."""
    llm = StubLlmClient([INTENT_JSON, SKILLS_JSON, V2_JSON, PRICING_JSON])
    fallback_called = []

    async def fake_fallback():
        fallback_called.append(True)
        return {"ok": True, "workflow_id": 99, "name": "AI 生成工作流"}

    events: list = []

    async def on_event(ev):
        events.append(ev)

    manifest = await run_pipeline(
        "我要一个能处理退款的客服助手",
        llm=llm,
        on_event=on_event,
        eligible_workflows=[],
        generate_workflow_fallback=fake_fallback,
    )
    assert manifest is not None
    assert fallback_called
    wf_done = next(
        (e for e in events if e["stage"] == "resolve_workflow" and e["event"] == "stage_done"), None
    )
    assert wf_done is not None
    assert wf_done["data"]["generated"] is True
    assert wf_done["data"]["workflow_id"] == 99


@pytest.mark.asyncio
async def test_pipeline_stage1_failure_aborts():
    """Path 3: parse_intent returns bad JSON → pipeline returns None."""
    llm = StubLlmClient(["not-json"])
    events: list = []

    async def on_event(ev):
        events.append(ev)

    manifest = await run_pipeline(
        "brief",
        llm=llm,
        on_event=on_event,
        eligible_workflows=[],
    )
    assert manifest is None
    error_ev = next((e for e in events if e.get("event") == "stage_error"), None)
    assert error_ev is not None
    assert error_ev["stage"] == "parse_intent"
    assert error_ev["retryable"] is True


@pytest.mark.asyncio
async def test_pipeline_skills_error_non_fatal():
    """Skills stage error should not abort the pipeline."""
    llm = StubLlmClient([INTENT_JSON, RANK_JSON_MATCH, "not-json-array", V2_JSON, PRICING_JSON])
    events: list = []

    async def on_event(ev):
        events.append(ev)

    manifest = await run_pipeline(
        "brief",
        llm=llm,
        on_event=on_event,
        eligible_workflows=[{"id": 42, "name": "退款工作流", "description": ""}],
    )
    assert manifest is not None  # pipeline still completes
    skill_err = next(
        (e for e in events if e["stage"] == "suggest_skills" and e["event"] == "stage_error"), None
    )
    assert skill_err is not None
    assert skill_err["retryable"] is False
