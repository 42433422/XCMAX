"""Schemas for workbench delivery."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from modstore_server.workbench.intent import CANVAS_SKILL_INTENT

_LOG = logging.getLogger("modstore_server.workbench_api")


class EmployeeAiDraftBody(BaseModel):
    brief: str = Field(..., min_length=3, max_length=8000)
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
    suggested_id: Optional[str] = Field(None, max_length=64)


class EmployeeAiRefinePromptBody(BaseModel):
    current_prompt: str = Field(..., min_length=1, max_length=16000)
    instruction: str = Field(..., min_length=3, max_length=2000)
    role_context: str = Field("", max_length=500)
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)


class WorkbenchResearchBody(BaseModel):
    brief: str = Field(..., min_length=3, max_length=4000)
    intent: Literal["workflow", "mod", "employee", "skill"] = "skill"
    max_repos: int = Field(3, ge=1, le=5)
    max_web: int = Field(6, ge=1, le=12, description="Tavily 网页摘要条数上限")
    max_chars: int = Field(8000, ge=2000, le=20000)


class WorkbenchWebSearchBody(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    max_results: int = Field(8, ge=1, le=12)
    max_chars: int = Field(8000, ge=1000, le=12000)


class WorkbenchSessionCreateBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intent: Literal["mod", "employee", "workflow", "skill"]
    brief: str = Field(..., min_length=3, max_length=30000)
    workflow_name: Optional[str] = Field(None, max_length=256)
    skill_group_name: Optional[str] = Field(
        None,
        max_length=256,
        description="画布 Skill 组名称；若填且未填 workflow_name，则写入 workflow_name",
    )
    plan_notes: Optional[str] = Field("", max_length=4000)
    suggested_mod_id: Optional[str] = Field(None, max_length=64)
    replace: bool = True
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
    generate_workflow_graph: bool = Field(
        True,
        description="为画布 intent（skill，旧称 workflow）时是否用 LLM 生成节点与边（false 则仅创建空 Skill 组容器）",
    )
    generate_full_suite: bool = Field(
        True, description="为 mod intent 时是否生成 Mod + 员工 + 工作流绑定的一体化套件"
    )
    generate_frontend: bool = Field(
        True,
        description="为 mod intent 时是否生成定制 Vue 前端页面；false 时仅保留最小前端占位",
    )
    planning_messages: List[Dict[str, Any]] = Field(default_factory=list)
    execution_checklist: List[str] = Field(default_factory=list)
    source_documents: List[Dict[str, Any]] = Field(default_factory=list)
    execution_mode: Literal["workflow", "script"] = "workflow"
    employee_target: Literal["pack_only", "pack_plus_workflow"] = Field(
        "pack_only",
        description="做员工：pack_only 仅生成包体；pack_plus_workflow 额外创建画布工作流并写回 manifest",
    )
    employee_workflow_name: Optional[str] = Field(
        None, max_length=256, description="pack_plus_workflow 时画布工作流名称（可选）"
    )
    fhd_base_url: Optional[str] = Field(
        None,
        max_length=512,
        description="可选 FHD 宿主根 URL，用于编排末尾 GET /api/mods/ 连通性探测",
    )
    embed_script_workflow: bool = Field(
        False,
        description="做员工：在生成员工包之前先走脚本生成/沙箱 pipeline，落库 ScriptWorkflow 并把 workflow_id 写入 employee_config_v2.collaboration.script_workflows",
    )

    @field_validator("intent", mode="before")
    @classmethod
    def _session_intent_alias(cls, v: object) -> object:
        if isinstance(v, str) and v.strip().lower() == "workflow":
            return CANVAS_SKILL_INTENT
        return v

    @model_validator(mode="before")
    @classmethod
    def _skill_group_name_merge(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        wn = (data.get("workflow_name") or "").strip()
        sg = (data.get("skill_group_name") or "").strip()
        if not wn and sg:
            data["workflow_name"] = sg
        return data

    @field_validator("execution_checklist", mode="before")
    @classmethod
    def _coerce_execution_checklist(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [str(x) for x in v]

    @field_validator("planning_messages", mode="before")
    @classmethod
    def _coerce_planning_messages(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, dict)]

    @field_validator("source_documents", mode="before")
    @classmethod
    def _coerce_source_documents(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [x for x in v if isinstance(x, dict)]


def _parse_workbench_session_create(meta: Dict[str, Any]) -> WorkbenchSessionCreateBody:
    """解析工作台创建会话体；把 Pydantic 校验失败转成可读中文 detail。"""
    try:
        return WorkbenchSessionCreateBody.model_validate(meta)
    except ValidationError as e:
        parts: List[str] = []
        for err in e.errors():
            loc = ".".join((str(x) for x in err.get("loc", ()) if str(x) != "body"))
            msg = str(err.get("msg") or "").strip()
            if loc:
                parts.append(f"{loc}: {msg}")
            elif msg:
                parts.append(msg)
        detail = "；".join(parts)[:1800] if parts else str(e)
        raise HTTPException(
            status_code=422, detail=f"工作台请求参数无效：{detail}"
        ) from e


class WorkbenchEdgeTtsBody(BaseModel):
    """与 Edge 浏览器「大声朗读」相同的在线神经语音（经 edge-tts 访问微软语音服务）。"""

    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field("zh-CN-XiaoxiaoNeural", max_length=120)
    rate: float = Field(
        1.0, ge=0.6, le=1.6, description="相对语速，约映射到 Edge 的 rate 百分比"
    )


class WorkbenchUnifiedTtsBody(BaseModel):
    """统一 TTS：优先 MiMo，失败回退 Edge 神经音。"""

    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(
        "", max_length=120, description="MiMo 音色（如 冰糖）；空则用默认"
    )
    edge_voice: str = Field("zh-CN-XiaoxiaoNeural", max_length=120)
    rate: float = Field(1.0, ge=0.6, le=1.6)


class WorkbenchVibeCodeSkillBody(BaseModel):
    """工作台「AI 代码技能」: NL → vibe-coding CodeSkill → 试跑 → 可选发布。"""

    brief: str = Field(..., min_length=3, max_length=8000)
    run_input: Dict[str, Any] = Field(default_factory=dict)
    skill_id: Optional[str] = Field(None, max_length=128)
    mode: Literal["brief_first", "direct"] = "brief_first"
    dry_run: bool = Field(False, description="为 True 时只生成代码 + 试跑,不上架")
    provider: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
    project_root: Optional[str] = Field(
        None,
        max_length=4096,
        description="可选：项目根目录（必须在用户工作区内）。非空时会先做目录扫描/技术栈分析并注入 brief，并把 project_analysis 自动加入 run_input，用于文档生成器/项目分析类 Skill。",
    )
    publish: Optional[Dict[str, Any]] = Field(
        None, description="非空时在试跑通过后调 SkillPublisher 上架到本 MODstore"
    )


class EmployeeBenchRequest(BaseModel):
    employee_id: str = Field(..., description="员工包 ID（同 pack_id）")
    provider: Optional[str] = Field(None)
    model: Optional[str] = Field(None)
    per_dimension_ids: Optional[Dict[str, str]] = Field(
        None,
        description="五维专属评分员工包映射 {维度键: employee_id}；有效键：manifest_compliance / declaration_completeness / api_testability_static / security_and_size / metadata_quality。合并优先级：环境变量 MODSTORE_AUDIT_DIM_* → LLM 自动从评审池挑选 → 本字段。未填满的维度可用服务端评审池（MODSTORE_BENCH_REVIEWER_POOL / *_FROM_CATALOG）自动补位。",
    )


class EmployeePublishRequest(BaseModel):
    employee_id: str = Field(..., description="员工包 ID（同 pack_id）")
    price: float = Field(0.0)
    industry: str = Field("通用", max_length=64)
    release_channel: str = Field("stable", max_length=32)


class EmployeeSyncTestRequest(BaseModel):
    employee_id: str = Field(..., description="员工包 ID（同 pack_id）")
    fhd_base_url: Optional[str] = Field(
        None,
        description="宿主 fhd-sandbox-runtime 的 base URL，如 http://localhost:9999",
    )
    provider: Optional[str] = Field(None)
    model: Optional[str] = Field(None)
    price: float = Field(0.0)
    industry: str = Field("通用", max_length=64)
    per_dimension_ids: Optional[Dict[str, str]] = Field(
        None,
        description="五维专属评分员工包映射 {维度键: employee_id}；与环境变量、自动评审池补位规则同 employee-bench-test。",
    )


class EmployeeSaveBody(BaseModel):
    manifest: Dict[str, Any] = Field(
        ..., description="员工完整 manifest（employee_config_v2 结构）"
    )
    employee_id: Optional[str] = Field(
        None,
        max_length=128,
        description="已有员工ID；为空时从 manifest.identity.id 读取",
    )
    provider: Optional[str] = Field(
        None,
        max_length=64,
        description="注册 vibe-coding Skill 用的 LLM 供应商（为空则尝试用户默认）",
    )
    model: Optional[str] = Field(
        None, max_length=128, description="注册 vibe-coding Skill 用的 LLM 模型"
    )
    register_skills: bool = Field(
        True, description="是否同时注册 vibe-coding ESkill（需要 LLM；失败不影响保存）"
    )


class EmployeeExportBody(BaseModel):
    manifest: Dict[str, Any] = Field(..., description="员工完整 manifest")
    employee_id: Optional[str] = Field(None, max_length=128)
    standalone: bool = Field(
        False,
        description="为 True 时在 zip 内额外写入 __main__.py 与 standalone/，可作为 zipapp 本地执行 python xxx.xcemp",
    )


class DispatchRequest(BaseModel):
    task_description: str = Field(..., min_length=1, max_length=2000)
    use_task_router: bool = Field(True, description="True 时 LLM 自动拆解子任务并路由")
    target_employee_id: Optional[str] = Field(
        None, description="use_task_router=False 时指定单员工"
    )
    max_concurrency: int = Field(2, ge=1, le=8)
    allow_high_risk_real_run: bool = Field(False)
    llm_provider: str = Field("auto")
    llm_model: str = Field("auto")
