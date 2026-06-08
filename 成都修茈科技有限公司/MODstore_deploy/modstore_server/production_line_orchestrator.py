"""制作线全流程编排器：双线 10+10 与五线映射共存。

═══ 五线（v9.1 产品视图）═══
  O-A 获客 · O-B 伙伴（投资企业进度汇报）
  P-W 网站 · P-M 用户 Mod · P-S 通用软件（2 SKU × Win/Mac/Android/iOS 四发布渠道）

═══ 双线（编排兼容层）═══
  制作线：Craft / Vibe / CI / 发布 / 监控
  运营线：获客 → CRM → 合同 → 交付 → 反馈 → 对账

═══ 交叉驱动 ═══
  运营反馈 → 制作编码 → 产出物 → 伙伴线交付 / 进度汇报

每条线内部还有子流程：
- 制作线步骤2(AI编码) = Craft 13步流水线(制作员工包) + Vibe-Coding(制作核心代码)
- 制作线步骤3(测试) = FHD CI(pytest/vitest/Playwright) + MODstore 沙箱
- 制作线步骤5(发布) = GitHub Release + K8s(rolling/canary/blue-green) + 宿主推送
- 运营线步骤5(收费) = MODstore 支付宝/微信 + FHD Token 钱包

红线操作通过审批门控：AI 执行 → 等待审批 → 审批通过后继续。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence

StepExecutor = Literal["fhd", "craft", "ci", "external", "admin"]

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalGate(str, Enum):
    NONE = "none"
    ADMIN = "admin"
    CI_PASS = "ci_pass"
    ADMIN_AND_CI = "admin_and_ci"


class LineType(str, Enum):
    PRODUCTION = "production"
    OPERATIONS = "operations"


class FiveLineId(str, Enum):
    """六线全自动：运营 2 + 制作 3 + 共享归档 1（见 FHD/docs/guides/FIVE_LINE_AUTOMATION.md）。"""

    OPS_ACQUISITION = "ops_acquisition"
    OPS_PARTNER = "ops_partner"
    PROD_WEB = "prod_web"
    PROD_MOD = "prod_mod"
    PROD_SOFTWARE = "prod_software"
    SHARED_RETENTION = "shared_retention"


@dataclass
class FlowStep:
    step_id: str
    name: str
    line: LineType
    description: str
    employee_ids: List[str]
    sub_steps: List[str] = field(default_factory=list)
    approval_gate: ApprovalGate = ApprovalGate.NONE
    auto_trigger_next: bool = True
    retry_on_failure: bool = True
    max_retries: int = 2
    timeout_seconds: int = 3600
    cross_line_trigger: Optional[str] = None
    executor: StepExecutor = "fhd"


PRODUCTION_LINE_STEPS: List[FlowStep] = [
    FlowStep(
        step_id="P1",
        name="官网建设与维护",
        line=LineType.PRODUCTION,
        description="xiu-ci.com 全站 = 成都修茈科技有限公司 monorepo · /market/workbench/home 管控中枢",
        employee_ids=[
            "site-content-editor",
            "seo-sitemap-curator",
            "marketing-site-builder",
            "flask-entry-keeper",
            "market-frontend-dev",
            "workbench-ux-stylist",
            "modstore-backend-api",
            "java-payment-bridge-officer",
            "nginx-config-engineer",
            "deploy-release-officer",
        ],
        sub_steps=[
            "营销静态站：根 *.html · marketing-site/ · ci-marketing-site.yml",
            "修茈市场 SPA：MODstore_deploy/market/ · /market/* · ci-market · market-live-deploy",
            "工作台中枢：/market/workbench/home · admin/orchestrate · yuangon/** · daily-orchestrator",
            "MODstore 后端：modstore_server/ · /api/* · java_payment · app.py · deploy.yml",
            "文档与 SEO：FHD/docs MkDocs · sitemap/robots · siteKnowledge.ts",
            "nginx 全站：nginx-xiu-ci.conf · /market/ SPA · /api/ upstream · 组件级 CI 部署",
        ],
        approval_gate=ApprovalGate.CI_PASS,
    ),
    FlowStep(
        step_id="P2",
        name="AI自动编码",
        line=LineType.PRODUCTION,
        description="Craft 13步流水线(员工包) + Vibe-Coding(核心代码) + FHD核心app/自动编码",
        employee_ids=[
            "intent-analyst",
            "employee-planner",
            "artifact-generator",
            "quality-validator",
            "miniapp-builder",
            "script-binder",
            "workflow-automator",
            "pack-registrar",
            "sandbox-tester",
            "code-validator",
            "self-checker",
            "host-checker",
            "hex-quality-assessor",
            "vibe-coding-maintainer",
        ],
        sub_steps=[
            "Craft spec: intent-analyst 解析需求 → 结构化意图 + 领域关键词",
            "Craft employee_plan: employee-planner 规划员工包架构蓝图",
            "Craft generate: artifact-generator LLM 生成 manifest + Python + 资产",
            "Craft validate: quality-validator manifest合规 + Python语法 + 资产完整性",
            "Craft script_workflow: miniapp-builder NL→可执行脚本逻辑",
            "Craft embed_script: script-binder 脚本嵌入员工包",
            "Craft workflow: workflow-automator NL→画布节点与连线",
            "Craft register_pack: pack-registrar 五维审核 + .xcemp 发布包",
            "Craft workflow_sandbox: sandbox-tester Mock执行验证",
            "Craft mod_sandbox: code-validator Python编译 + 包体一致性",
            "Craft standalone_smoke: self-checker 隔离环境自检(含自动修复)",
            "Craft host_check: host-checker 宿主连通性 + LLM密钥",
            "Craft six_dim_gate: hex-quality-assessor 六维评估 + LLM增强",
            "Vibe-Coding: code_factory brief_first模式 → 规约→代码→验证→修复",
            "FHD 核心: fhd-core-maintainer → CR/PR 闭环（fhd-core-coding-loop.yml）",
        ],
        approval_gate=ApprovalGate.ADMIN_AND_CI,
    ),
    FlowStep(
        step_id="P3",
        name="自动测试",
        line=LineType.PRODUCTION,
        description="FHD CI(pytest/vitest/Playwright) + MODstore沙箱 + 覆盖率门禁",
        employee_ids=["test-qa-runner", "sandbox-tester", "code-validator", "self-checker"],
        sub_steps=[
            "FHD CI: backend-test(pytest + 覆盖率60%门禁) + frontend-build(vitest + vue-tsc)",
            "FHD CI: frontend-e2e(Playwright smoke+core+navigation)",
            "FHD CI: backend-lint(Black/isort/Flake8/MyPy) + backend-security(Bandit+Safety)",
            "FHD CI: backend-governance-verify(OpenAPI快照漂移检测)",
            "MODstore CI: modstore-tests(pytest + 覆盖率40%门禁)",
            "Mod 沙盒镜像构建 smoke（FHD test.yml mod-sandbox-smoke）",
            "test-qa-runner 自动生成测试骨架（skill-generate-pytest-stub）",
        ],
        approval_gate=ApprovalGate.CI_PASS,
    ),
    FlowStep(
        step_id="P4",
        name="自动构建打包",
        line=LineType.PRODUCTION,
        description="后端构建 · 前端构建 · Electron双SKU · Docker镜像 · Mod打包",
        employee_ids=["pack-registrar", "deploy-release-officer", "mobile-android-release-officer"],
        sub_steps=[
            "FHD CI: docker-build(backend + frontend 镜像推 GHCR)",
            "release-desktop: Windows/macOS 双SKU(build-all-skus.ps1 + build-installer.sh)",
            "release-web: Docker镜像打版本tag + latest",
            "stage-bundled-mods + verify-bundled-mods: 按 SKU 暂存打包 Mod",
            "generate-update-metadata.mjs: electron-updater 元数据 + Ed25519 签名",
        ],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="P5",
        name="自动发布",
        line=LineType.PRODUCTION,
        description="GitHub Release + K8s部署(rolling/canary/blue-green) + 宿主推送",
        employee_ids=[
            "deploy-release-officer",
            "change-request-auditor",
            "mobile-android-release-officer",
            "mobile-ios-release-officer",
        ],
        sub_steps=[
            "deploy.yml: build-and-push → deploy-staging → deploy-production",
            "deploy-canary: 金丝雀10%流量 + HPA自动扩缩",
            "deploy-blue-green: 蓝绿部署 + DEPLOY_BG_AUTO_PROMOTE 自动切流量",
            "NeuroBus 环境变量注入(dedup/circuit/rate_limit/trace/lifeline/dlq/sla_log)",
            "GitHub Release: softprops/action-gh-release + generate_release_notes",
        ],
        approval_gate=ApprovalGate.ADMIN_AND_CI,
    ),
    FlowStep(
        step_id="P6",
        name="自动推送更新",
        line=LineType.PRODUCTION,
        description="electron-updater + Ed25519签名 + Mod索引 + SKU上传",
        employee_ids=["push-update-context-officer"],
        sub_steps=[
            "electron-updater: latest.yml / latest-mac.yml 自动更新",
            "Ed25519 签名校验(XCAGI_UPDATE_ED25519_PRIVATE_KEY)",
            "upload-release-skus.ps1: 双SKU上传",
            "generate_mods_index.py: Mod索引更新",
            "release-desktop 后 sync-xcagi-releases-to-cos.sh（SSH）",
            "Mod 桌面 OTA 拉取（mod-ota-publish.yml）",
        ],
        approval_gate=ApprovalGate.CI_PASS,
    ),
    FlowStep(
        step_id="P7",
        name="运行时监控",
        line=LineType.PRODUCTION,
        description="NeuroBus 12域监控 + K8s监控栈 + 异常自动修复闭环",
        employee_ids=["log-monitor-incident", "host-checker"],
        sub_steps=[
            "NeuroBus: 12神经域事件流 + 8可靠性机制(去重/限流/熔断/保命/追踪/SLA/DLQ/采样)",
            "K8s: Prometheus + Grafana + Loki + Alertmanager",
            "incident_bus: 员工事件派发 + Redis Streams 双写",
            "auto_fix_loop: anomaly.detected → daily-orchestrator → CR → 审批 → 落盘",
            "异常→自动修复闭环(已补齐)",
        ],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="P8",
        name="自动净化优化",
        line=LineType.PRODUCTION,
        description="CVE自动修复PR + 技术债清理 + 依赖更新 + 安全审计 + 代码重构",
        employee_ids=[
            "retention-officer",
            "security-secrets-guard",
            "daily-orchestrator",
            "legacy-archive-curator",
        ],
        sub_steps=[
            "CI: Bandit + Safety + gitleaks + pre-release-security.ps1",
            "auto_fix_loop: cve.detected → 自动patch requirements → CR → 审批 → PR",
            "daily-orchestrator: 每日最小修复(测试失败/日志告警) → 审批队列",
            "retention-officer: 过期文件清理(每日03:15)",
            "AI 驱动重构(待补齐)",
        ],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="P9",
        name="版本自动演进",
        line=LineType.PRODUCTION,
        description="自动bump版本 + 同步7锚点 + 生成CHANGELOG + DB迁移",
        employee_ids=["deploy-release-officer", "dbops-engineer", "push-update-context-officer"],
        sub_steps=[
            "auto_version_bump: git log判断bump类型 → 同步7锚点(pyproject/package.json/fastapi_app/manifest)",
            "auto_version_bump: 生成CHANGELOG条目 → prepend到CHANGELOG.md",
            "auto_version_bump: 更新VERSION.md + release/VERSION",
            "Alembic: 20+ 迁移版本 + dbops-engineer 审核",
            "semantic-release.yml（conventional commits → bump + CHANGELOG）",
            "XCAGI_RELEASE_AI_GATE 遥测门控发版",
        ],
        approval_gate=ApprovalGate.ADMIN_AND_CI,
    ),
    FlowStep(
        step_id="P10",
        name="AI自驱迭代",
        line=LineType.PRODUCTION,
        description="遥测→backlog→auto-PR闭环 + 员工自进化 + 需求→制作线交叉驱动",
        employee_ids=["intake-dispatcher", "task-router-officer", "daily-orchestrator"],
        sub_steps=[
            "telemetry_backlog_loop: 扫描员工执行指标 + 覆盖率趋势 + CI失败率 + market_signal",
            "telemetry_backlog_loop: 信号→建议单→派发→CR→PR（FHD /api/internal/telemetry/ingest）",
            "market_signal 扫描 → release_planning 建议单（下一版本候选，不自动发版）",
            "employee_evolution: 高频失败员工→LLM优化prompt→suggestion",
            "OPS_CLOSURE: 桌面↔官网值班派发 → 需求回流制作线",
            "运营线反馈→制作线需求(交叉驱动)",
        ],
        approval_gate=ApprovalGate.ADMIN,
        cross_line_trigger="O7",
    ),
]

OPERATIONS_LINE_STEPS: List[FlowStep] = [
    FlowStep(
        step_id="O1",
        name="获客引流",
        line=LineType.OPERATIONS,
        description="官网营销 + 下载页 + 联系表单 + SEO",
        employee_ids=["site-content-editor", "marketing-site-builder"],
        sub_steps=[
            "xiu-ci.com 营销静态站(Nunjucks + CI)",
            "SoftwareDownloadView 双SKU下载页",
            "HomeView 联系表单 → landing_contact_submissions",
            "Android Firebase Analytics(XcagiAnalytics.kt)",
        ],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="O2",
        name="CRM与需求收集",
        line=LineType.OPERATIONS,
        description="客户主数据 + AI客服 + 工单 + 需求接入",
        employee_ids=["user-customer-service-officer", "intake-dispatcher"],
        sub_steps=[
            "FHD ERP: /api/customers/list 客户主数据",
            "MODstore: customer_service_api AI客服 + 工单",
            "intake-dispatcher: 外部输入→结构化task→待派发队列",
            "OPS_CLOSURE: 桌面↔官网值班派发",
        ],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="O3",
        name="报价与合同",
        line=LineType.OPERATIONS,
        description="价目表 + 合同生成 + SKU定价",
        employee_ids=["modstore-backend-api"],
        sub_steps=[
            "MODstore: PaymentPlansView 会员套餐/SKU定价",
            "价目表 Word 导出 + 合同 Excel 生成",
        ],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="O4",
        name="收费",
        line=LineType.OPERATIONS,
        description="支付宝/微信 + Token钱包 + 订阅续费",
        employee_ids=["payment-billing-reconciler"],
        sub_steps=[
            "MODstore: 支付宝 + 微信(Java PaymentController + PostgreSQL)",
            "FHD: Token钱包(model_payment) + LLM计费",
            "MODstore: subscription_renewer 订阅续费",
            "双栈统一(待补齐: FHD JSON→PostgreSQL)",
        ],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="O5",
        name="软件交付",
        line=LineType.OPERATIONS,
        description="Electron双SKU + Docker/K8s + License + 下载",
        employee_ids=["deploy-release-officer"],
        sub_steps=[
            "Electron: Windows/macOS 双SKU安装包",
            "Docker: docker-compose 5服务(backend/celery/redis/postgres/frontend)",
            "K8s: deployment + HPA + ingress + 网络策略",
            "License: LanCidrGuard + LanLicenseGuard",
            "deliverable-status + XcagiDownloader",
        ],
        approval_gate=ApprovalGate.ADMIN_AND_CI,
    ),
    FlowStep(
        step_id="O6",
        name="用户使用",
        line=LineType.OPERATIONS,
        description="AI对话→意图识别→领域处理→业务操作",
        employee_ids=["enterprise-adoption-officer", "user-customer-service-officer"],
        sub_steps=[
            "三层意图识别: ReflexArc(<1ms) → BERT(~100ms) → DeepSeek(~1s)",
            "NeuroBus 12域: intent→shipment→inventory→product→customer→order→payment→ocr→print→wechat→ai_service→safety",
            "Mod动态加载: mod_manager.scan→load→register_routes",
            "AI对话: AIChatApplicationService.process_chat → LLMWorkflowPlanner → HybridRiskGate → WorkflowEngine",
        ],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="O7",
        name="用户反馈",
        line=LineType.OPERATIONS,
        description="审批流 + 客服工单 + 变更请求 → 交叉驱动制作线",
        employee_ids=["user-customer-service-officer", "change-request-auditor"],
        sub_steps=[
            "FHD: approval-hub 审批流程引擎",
            "MODstore: Admin变更请求 + employee_change_request_api",
            "OPS_CLOSURE: 桌面↔官网值班派发",
            "→ 交叉触发制作线P2(AI自动编码)和P10(AI自驱迭代)",
        ],
        approval_gate=ApprovalGate.NONE,
        cross_line_trigger="P2",
    ),
    FlowStep(
        step_id="O8",
        name="交付确认",
        line=LineType.OPERATIONS,
        description="QA验收 + 交付物冒烟 + 客户签收",
        employee_ids=["delivery-receipt-officer", "test-qa-runner"],
        sub_steps=[
            "ACCEPTANCE_GOVERNANCE + deliverable_smoke",
            "客户UAT签收(待补齐)",
        ],
        approval_gate=ApprovalGate.CI_PASS,
    ),
    FlowStep(
        step_id="O9",
        name="单据处理",
        line=LineType.OPERATIONS,
        description="价目表/合同/发票生成",
        employee_ids=["modstore-backend-api"],
        sub_steps=[
            "模板注册表 + 价目表/合同 Excel·Word 生成",
            "MODstore invoice_api MVP",
            "支付成功自动开票(待补齐)",
        ],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="O10",
        name="自动对账",
        line=LineType.OPERATIONS,
        description="reconciliation + 支付对账 + 告警闭环",
        employee_ids=["payment-billing-reconciler"],
        sub_steps=[
            "MODstore: reconciliation.py(preview/generate/confirm)",
            "payment-billing-reconciler 编制员工",
            "定时全自动对账+告警闭环(RECONCILIATION_AUTO_CONFIRM + /api/operations-line/reconciliation/run)",
        ],
        approval_gate=ApprovalGate.ADMIN,
    ),
]

PARTNER_LINE_STEPS: List[FlowStep] = [
    FlowStep(
        step_id="B1",
        name="生态伙伴接入",
        line=LineType.OPERATIONS,
        description="onboarding · 租户隔离 · 联合 SSO",
        employee_ids=["ecosystem-partner-onboard-officer", "modstore-backend-api"],
        sub_steps=["伙伴档案 · 租户隔离策略 · SSO 联合接入"],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="B2",
        name="联合 SKU catalog",
        line=LineType.OPERATIONS,
        description="生态产品挂载 · MODstore catalog 扩展",
        employee_ids=["ecosystem-joint-catalog-officer", "employee-pack-curator"],
        sub_steps=["联合 SKU · catalog 可见性 · 伙伴商品挂载"],
        approval_gate=ApprovalGate.ADMIN,
    ),
    FlowStep(
        step_id="B3",
        name="生态交付回传",
        line=LineType.OPERATIONS,
        description="联合包遥测 · 回写 O-A 进度快照",
        employee_ids=["ecosystem-delivery-reporter", "enterprise-adoption-officer"],
        sub_steps=["里程碑事件 · CRM 快照回写 · 联合包遥测"],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="B4",
        name="投资方只读视图",
        line=LineType.OPERATIONS,
        description="里程碑 · 风险 · 只读 Portal",
        employee_ids=["ecosystem-investor-portal-officer", "market-frontend-dev"],
        sub_steps=["只读 Portal · 里程碑视图 · 风险指标"],
        approval_gate=ApprovalGate.NONE,
    ),
    FlowStep(
        step_id="B5",
        name="生态分润对账",
        line=LineType.OPERATIONS,
        description="渠道分润 · 联合 GMV 对账",
        employee_ids=["ecosystem-revenue-share-reconciler", "payment-billing-reconciler"],
        sub_steps=["分润规则 · GMV 汇总 · 对账闭环"],
        approval_gate=ApprovalGate.ADMIN,
    ),
]

_STEP_EXECUTOR_MAP: Dict[str, StepExecutor] = {
    "P1": "external",
    "P2": "craft",
    "P3": "ci",
    "P4": "ci",
    "P5": "admin",
    "P6": "ci",
    "P7": "fhd",
    "P8": "admin",
    "P9": "admin",
    "P10": "fhd",
    "O1": "external",
    "O2": "fhd",
    "O3": "admin",
    "O4": "admin",
    "O5": "ci",
    "O6": "fhd",
    "O7": "admin",
    "O8": "ci",
    "O9": "admin",
    "O10": "admin",
    "B1": "admin",
    "B2": "admin",
    "B3": "fhd",
    "B4": "external",
    "B5": "admin",
}

_STATIC_SKIP_STEP_IDS = frozenset({"P4", "O1", "O3", "O4", "O5", "O6", "O8", "O9", "O10"})


def _bind_step_executors(steps: List[FlowStep]) -> List[FlowStep]:
    return [replace(s, executor=_STEP_EXECUTOR_MAP.get(s.step_id, "fhd")) for s in steps]


PRODUCTION_LINE_STEPS = _bind_step_executors(PRODUCTION_LINE_STEPS)
OPERATIONS_LINE_STEPS = _bind_step_executors(OPERATIONS_LINE_STEPS)
PARTNER_LINE_STEPS = _bind_step_executors(PARTNER_LINE_STEPS)
ALL_STEPS: List[FlowStep] = PRODUCTION_LINE_STEPS + OPERATIONS_LINE_STEPS + PARTNER_LINE_STEPS


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    approval_id: Optional[int] = None


class ProductionLineOrchestrator:
    def __init__(self):
        self._step_results: Dict[str, StepResult] = {}
        self._callbacks: Dict[str, Callable] = {}
        self._running = False

    def register_callback(self, event: str, callback: Callable) -> None:
        self._callbacks[event] = callback

    def _fire(self, event: str, **kwargs) -> Any:
        cb = self._callbacks.get(event)
        if cb:
            return cb(**kwargs)
        return None

    def get_step(self, step_id: str) -> Optional[FlowStep]:
        for s in ALL_STEPS:
            if s.step_id == step_id:
                return s
        return None

    def get_step_status(self, step_id: str) -> StepStatus:
        r = self._step_results.get(step_id)
        return r.status if r else StepStatus.PENDING

    def get_pipeline_status(self) -> Dict[str, Any]:
        production_steps = []
        for s in PRODUCTION_LINE_STEPS:
            r = self._step_results.get(s.step_id)
            production_steps.append(
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": r.status.value if r else "pending",
                    "executor": s.executor,
                    "approval_gate": s.approval_gate.value,
                    "sub_steps": s.sub_steps,
                    "cross_line_trigger": s.cross_line_trigger,
                }
            )

        operations_steps = []
        for s in OPERATIONS_LINE_STEPS:
            r = self._step_results.get(s.step_id)
            operations_steps.append(
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "status": r.status.value if r else "pending",
                    "executor": s.executor,
                    "approval_gate": s.approval_gate.value,
                    "sub_steps": s.sub_steps,
                    "cross_line_trigger": s.cross_line_trigger,
                }
            )

        p_completed = sum(1 for s in production_steps if s["status"] == "completed")
        o_completed = sum(1 for s in operations_steps if s["status"] == "completed")

        return {
            "production_line": {
                "total": len(PRODUCTION_LINE_STEPS),
                "completed": p_completed,
                "automation_rate": round(p_completed / len(PRODUCTION_LINE_STEPS) * 100, 1),
                "steps": production_steps,
            },
            "operations_line": {
                "total": len(OPERATIONS_LINE_STEPS),
                "completed": o_completed,
                "automation_rate": round(o_completed / len(OPERATIONS_LINE_STEPS) * 100, 1),
                "steps": operations_steps,
            },
            "overall_automation_rate": round(
                (p_completed + o_completed)
                / (len(PRODUCTION_LINE_STEPS) + len(OPERATIONS_LINE_STEPS))
                * 100,
                1,
            ),
        }

    async def run_step(self, step_id: str, context: Optional[Dict[str, Any]] = None) -> StepResult:
        step = self.get_step(step_id)
        if not step:
            return StepResult(step_id=step_id, status=StepStatus.FAILED, error="step not found")

        self._step_results[step_id] = StepResult(step_id=step_id, status=StepStatus.RUNNING)
        self._fire("step_started", step_id=step_id, step_name=step.name, line=step.line.value)

        try:
            result_data = await self._execute_step(step, context or {})

            if step.approval_gate != ApprovalGate.NONE:
                self._step_results[step_id] = StepResult(
                    step_id=step_id,
                    status=StepStatus.AWAITING_APPROVAL,
                    data=result_data,
                )
                self._fire(
                    "step_awaiting_approval",
                    step_id=step_id,
                    step_name=step.name,
                    gate=step.approval_gate.value,
                )
                return self._step_results[step_id]

            self._step_results[step_id] = StepResult(
                step_id=step_id,
                status=StepStatus.COMPLETED,
                data=result_data,
            )
            self._fire("step_completed", step_id=step_id, step_name=step.name)

            if step.cross_line_trigger:
                self._fire("cross_line_trigger", from_step=step_id, to_step=step.cross_line_trigger)

            ctx = context or {}
            if step.auto_trigger_next and not getattr(self, "_release_train_subset", False):
                next_step = self._get_next_step(step)
                if next_step:
                    return await self.run_step(next_step.step_id, context=result_data)

            return self._step_results[step_id]

        except Exception as exc:
            logger.exception("pipeline step %s failed: %s", step_id, exc)
            self._step_results[step_id] = StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                error=str(exc),
            )
            self._fire("step_failed", step_id=step_id, step_name=step.name, error=str(exc))

            if step.retry_on_failure and step.max_retries > 0:
                return await self._retry_step(step, context, remaining=step.max_retries)

            return self._step_results[step_id]

    def _get_next_step(self, step: FlowStep) -> Optional[FlowStep]:
        if step.line == LineType.PRODUCTION:
            steps = PRODUCTION_LINE_STEPS
        else:
            steps = OPERATIONS_LINE_STEPS
        idx = next((i for i, s in enumerate(steps) if s.step_id == step.step_id), -1)
        if 0 <= idx < len(steps) - 1:
            return steps[idx + 1]
        return None

    async def _retry_step(
        self, step: FlowStep, context: Optional[Dict], remaining: int
    ) -> StepResult:
        logger.info("retrying step %s (%s), remaining=%d", step.step_id, step.name, remaining)
        try:
            result_data = await self._execute_step(step, context or {})
            self._step_results[step.step_id] = StepResult(
                step_id=step.step_id,
                status=StepStatus.COMPLETED,
                data=result_data,
            )
            self._fire("step_completed", step_id=step.step_id, step_name=step.name)
            return self._step_results[step.step_id]
        except Exception as exc:
            if remaining > 1:
                return await self._retry_step(step, context, remaining - 1)
            self._step_results[step.step_id] = StepResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=str(exc),
            )
            self._fire("step_failed", step_id=step.step_id, step_name=step.name, error=str(exc))
            return self._step_results[step.step_id]

    async def _execute_step(self, step: FlowStep, context: Dict[str, Any]) -> Dict[str, Any]:
        executor_map = {
            "P1": self._step_site_and_seo,
            "P2": self._step_ai_coding,
            "P3": self._step_auto_test,
            "P4": self._step_build_and_package,
            "P5": self._step_auto_release,
            "P6": self._step_push_updates,
            "P7": self._step_runtime_monitor,
            "P8": self._step_auto_purify,
            "P9": self._step_version_evolution,
            "P10": self._step_ai_self_driven,
            "O1": self._step_acquisition,
            "O2": self._step_crm,
            "O3": self._step_quotation,
            "O4": self._step_payment,
            "O5": self._step_delivery,
            "O6": self._step_usage,
            "O7": self._step_feedback,
            "O8": self._step_acceptance,
            "O9": self._step_documents,
            "O10": self._step_reconciliation,
        }
        fn = executor_map.get(step.step_id)
        if fn:
            return await fn(context)
        return {"step": step.step_id, "result": {"ok": True, "message": f"{step.name} executed"}}

    async def approve_step(self, step_id: str, admin_user_id: int = 0) -> StepResult:
        step = self.get_step(step_id)
        if not step:
            return StepResult(step_id=step_id, status=StepStatus.FAILED, error="step not found")

        current = self._step_results.get(step_id)
        if not current or current.status != StepStatus.AWAITING_APPROVAL:
            return StepResult(
                step_id=step_id, status=StepStatus.FAILED, error="step not awaiting approval"
            )

        self._step_results[step_id] = StepResult(
            step_id=step_id,
            status=StepStatus.APPROVED,
            data=current.data,
            approval_id=admin_user_id or None,
        )
        self._fire(
            "step_approved", step_id=step_id, step_name=step.name, admin_user_id=admin_user_id
        )

        self._step_results[step_id] = StepResult(
            step_id=step_id,
            status=StepStatus.COMPLETED,
            data=current.data,
        )
        self._fire("step_completed", step_id=step_id, step_name=step.name)

        if step.cross_line_trigger:
            self._fire("cross_line_trigger", from_step=step_id, to_step=step.cross_line_trigger)

        ctx = current.data if isinstance(current.data, dict) else {}
        if step.auto_trigger_next and not getattr(self, "_release_train_subset", False):
            next_step = self._get_next_step(step)
            if next_step:
                return await self.run_step(next_step.step_id, context=current.data)

        return self._step_results[step_id]

    async def reject_step(
        self, step_id: str, admin_user_id: int = 0, reason: str = ""
    ) -> StepResult:
        current = self._step_results.get(step_id)
        if not current or current.status != StepStatus.AWAITING_APPROVAL:
            return StepResult(
                step_id=step_id, status=StepStatus.FAILED, error="step not awaiting approval"
            )

        self._step_results[step_id] = StepResult(
            step_id=step_id,
            status=StepStatus.REJECTED,
            data=current.data,
            error=reason,
        )
        self._fire("step_rejected", step_id=step_id, admin_user_id=admin_user_id, reason=reason)
        return self._step_results[step_id]

    async def run_full_pipeline(
        self,
        line: LineType = LineType.PRODUCTION,
        start_from: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._running = True
        steps = PRODUCTION_LINE_STEPS if line == LineType.PRODUCTION else OPERATIONS_LINE_STEPS
        self._fire("pipeline_started", line=line.value, start_from=start_from)

        current_context = context or {}
        if current_context.get("release_train_subset"):
            self._release_train_subset = True
        started = start_from is None

        for step in steps:
            if not started:
                if step.step_id == start_from:
                    started = True
                else:
                    continue
            if not self._running:
                break

            result = await self.run_step(step.step_id, context=current_context)
            if result.status == StepStatus.AWAITING_APPROVAL:
                self._fire("pipeline_paused", step_id=step.step_id, reason="awaiting approval")
                return {
                    "ok": True,
                    "paused": True,
                    "paused_at_step": step.step_id,
                    "paused_at_name": step.name,
                    "line": line.value,
                    "message": f"步骤 {step.step_id}({step.name}) 等待审批后继续",
                    "pipeline_status": self.get_pipeline_status(),
                }

            if result.status == StepStatus.FAILED:
                self._fire("pipeline_failed", step_id=step.step_id, error=result.error)
                return {
                    "ok": False,
                    "failed_at_step": step.step_id,
                    "failed_at_name": step.name,
                    "line": line.value,
                    "error": result.error,
                    "pipeline_status": self.get_pipeline_status(),
                }

            current_context = result.data

        self._running = False
        self._fire("pipeline_completed", line=line.value)
        return {
            "ok": True,
            "paused": False,
            "line": line.value,
            "message": f"{'制作线' if line == LineType.PRODUCTION else '运营线'}全流程完成",
            "pipeline_status": self.get_pipeline_status(),
        }

    async def run_pipeline_steps(
        self,
        step_ids: Sequence[str],
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """按给定 step_id 列表顺序执行（用于 digest release_train Phase C 子集）。"""
        wanted = [str(s).strip().upper() for s in step_ids if str(s).strip()]
        if not wanted:
            return {"ok": True, "skipped": True, "reason": "empty step_ids"}

        self._running = True
        self._fire("pipeline_started", line=LineType.PRODUCTION.value, start_from=wanted[0])
        current_context = context or {}
        if current_context.get("release_train_subset"):
            self._release_train_subset = True
        executed: List[str] = []

        for step_id in wanted:
            if not self._running:
                break
            result = await self.run_step(step_id, context=current_context)
            executed.append(step_id)
            if result.status == StepStatus.AWAITING_APPROVAL:
                self._fire("pipeline_paused", step_id=step_id, reason="awaiting approval")
                return {
                    "ok": True,
                    "paused": True,
                    "paused_at_step": step_id,
                    "executed_steps": executed,
                    "pipeline_status": self.get_pipeline_status(),
                }
            if result.status == StepStatus.FAILED:
                self._fire("pipeline_failed", step_id=step_id, error=result.error)
                return {
                    "ok": False,
                    "failed_at_step": step_id,
                    "executed_steps": executed,
                    "error": result.error,
                    "pipeline_status": self.get_pipeline_status(),
                }
            current_context = result.data

        self._running = False
        self._fire("pipeline_completed", line=LineType.PRODUCTION.value)
        return {
            "ok": True,
            "paused": False,
            "executed_steps": executed,
            "pipeline_status": self.get_pipeline_status(),
        }

    def stop_pipeline(self) -> None:
        self._running = False
        self._fire("pipeline_stopped")

    def _skipped_step_result(
        self,
        step: FlowStep,
        message: str,
    ) -> Dict[str, Any]:
        """静态步：由 CI/外部系统/admin 门控完成，编排器不 dispatch 员工。"""
        return {
            "step": step.step_id,
            "result": {
                "ok": True,
                "skipped": True,
                "executor": step.executor,
                "message": message,
            },
        }

    async def _step_site_and_seo(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "更新官网内容、SEO站点地图、robots.txt、营销站构建；确保所有页面可访问、SEO合规。",
            context,
            target_employee_id="site-content-editor",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P1", "result": out}

    async def _step_ai_coding(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.craft_executor import (
            CRAFT_PIPELINE_ORDER,
            CRAFT_STEP_EMPLOYEE_MAP,
            dispatch_craft_step,
        )

        results = {}
        for employee_id in CRAFT_PIPELINE_ORDER:
            step_id = next(
                (s for s, e in CRAFT_STEP_EMPLOYEE_MAP.items() if e == employee_id),
                employee_id,
            )
            try:
                r = await dispatch_craft_step(step_id, **context)
                results[employee_id] = r
            except Exception as exc:
                logger.warning("craft step %s failed: %s", step_id, exc)
                results[employee_id] = {"ok": False, "error": str(exc)}
        fhd_out: Dict[str, Any] = {}
        try:
            from modstore_server.employee_orchestrator import plan_and_dispatch

            fhd_out = plan_and_dispatch(
                context.get("task_description")
                or "根据运营线反馈或遥测 backlog 修复 FHD app/ 并提交 PR。",
                context,
                target_employee_id="fhd-core-maintainer",
                created_by_user_id=int(context.get("created_by_user_id") or 0),
                include_dependencies=True,
            )
        except Exception as exc:
            logger.warning("fhd-core-maintainer dispatch failed: %s", exc)
            fhd_out = {"ok": False, "error": str(exc)}
        return {"step": "P2", "craft_results": results, "fhd_core": fhd_out}

    async def _step_auto_test(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "运行全站测试套件：pytest+vitest+Playwright E2E+覆盖率门禁；报告失败项并尝试自动修复。",
            context,
            target_employee_id="test-qa-runner",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P3", "result": out}

    async def _step_build_and_package(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("P4")
        assert step
        return self._skipped_step_result(step, "构建打包已由 CI 工作流自动完成")

    async def _step_auto_release(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        strategy = os.environ.get("XCAGI_DEPLOY_STRATEGY", "canary").strip().lower()
        out = plan_and_dispatch(
            f"执行自动发布：GitHub Release+更新元数据+{strategy}策略部署到K8s；"
            f"先部署到staging验证，再推进到production。",
            context,
            target_employee_id="deploy-release-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P5", "result": out, "strategy": strategy}

    async def _step_push_updates(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "推送更新：生成electron-updater元数据+Ed25519签名+Mod索引更新+上传发布SKU。",
            context,
            target_employee_id="push-update-context-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P6", "result": out}

    async def _step_runtime_monitor(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "运行时监控：采集日志+异常检测+告警摘要+熔断状态检查；发现问题触发自动修复。",
            context,
            target_employee_id="log-monitor-incident",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P7", "result": out}

    async def _step_auto_purify(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "自动净化：CVE扫描+依赖更新+技术债清理+过期文件清理+安全审计；"
            "低风险自动修复，高风险提交审批。",
            context,
            target_employee_id="daily-orchestrator",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "P8", "result": out}

    async def _step_version_evolution(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.auto_version_bump import auto_version_bump
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = str(repo_root())
        out = auto_version_bump(root)
        return {"step": "P9", "result": out}

    async def _step_ai_self_driven(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.telemetry_backlog_loop import run_telemetry_scan

        out = run_telemetry_scan()
        return {"step": "P10", "result": out}

    async def _step_acquisition(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O1")
        assert step
        return self._skipped_step_result(step, "获客引流由官网与 SEO 流水线自动完成")

    async def _step_crm(self, context: Dict[str, Any]) -> Dict[str, Any]:
        import os

        import httpx

        health: Dict[str, Any] = {}
        fhd = (os.environ.get("XCAGI_FHD_INTERNAL_URL") or "").rstrip("/")
        if fhd:
            try:
                resp = httpx.get(f"{fhd}/api/operations-line/health", timeout=10.0)
                if resp.status_code < 400:
                    payload = resp.json()
                    health = payload.get("data") if isinstance(payload, dict) else {}
            except Exception:
                pass
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "处理客户需求：AI客服对话+工单分类+需求结构化→待派发队列。",
            context,
            target_employee_id="user-customer-service-officer",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "O2", "result": out, "operations_health": health}

    async def _step_quotation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O3")
        assert step
        return self._skipped_step_result(step, "报价与合同在 admin 审批门控后由业务系统完成")

    async def _step_payment(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O4")
        assert step
        return self._skipped_step_result(
            step, "收费由支付系统（PostgreSQL SoT）自动处理，需 admin 审批"
        )

    async def _step_delivery(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O5")
        assert step
        return self._skipped_step_result(step, "软件交付由 CI/CD 与 K8s 发布流水线自动完成")

    async def _step_usage(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O6")
        assert step
        return self._skipped_step_result(step, "用户使用由 FHD 运行时与 NeuroBus 自动处理")

    async def _step_feedback(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from modstore_server.employee_orchestrator import plan_and_dispatch

        out = plan_and_dispatch(
            "处理用户反馈：审批流+变更请求+OPS_CLOSURE值班派发→交叉驱动制作线。",
            context,
            target_employee_id="change-request-auditor",
            created_by_user_id=0,
            include_dependencies=True,
        )
        return {"step": "O7", "result": out}

    async def _step_acceptance(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O8")
        assert step
        return self._skipped_step_result(step, "交付确认由 QA 验收与 CI 门控完成")

    async def _step_documents(self, context: Dict[str, Any]) -> Dict[str, Any]:
        step = self.get_step("O9")
        assert step
        return self._skipped_step_result(step, "单据处理在 admin 审批后由模板引擎完成")

    async def _step_reconciliation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        import os

        import httpx

        step = self.get_step("O10")
        assert step
        fhd = (
            os.environ.get("XCAGI_FHD_INTERNAL_URL") or os.environ.get("FHD_INTERNAL_URL") or ""
        ).rstrip("/")
        auto = (os.environ.get("RECONCILIATION_AUTO_CONFIRM") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if fhd and auto:
            try:
                resp = httpx.post(
                    f"{fhd}/api/operations-line/reconciliation/run",
                    params={"dry_run": "false"},
                    timeout=120.0,
                )
                if resp.status_code < 400:
                    payload = (
                        resp.json()
                        if resp.headers.get("content-type", "").startswith("application/json")
                        else {}
                    )
                    inner = payload.get("data") if isinstance(payload, dict) else {}
                    return {
                        "step": "O10",
                        "result": inner or payload,
                        "auto_reconciliation": True,
                    }
            except Exception as exc:
                return {
                    "step": "O10",
                    "result": {"ok": False, "error": str(exc)[:300]},
                    "auto_reconciliation": False,
                }
        note = (
            "已配置全自动对账时请设置 RECONCILIATION_AUTO_CONFIRM=1 与 XCAGI_FHD_INTERNAL_URL；"
            "否则在 admin 确认 draft 报告或 POST /api/operations-line/reconciliation/run"
        )
        return self._skipped_step_result(step, note)


@dataclass(frozen=True)
class FiveLineDefinition:
    line_id: FiveLineId
    name: str
    subtitle: str
    step_ids: tuple[str, ...]
    baseline_automation_rate: float
    release_channels: tuple[str, ...] = ()
    channel_notes: Dict[str, str] = field(default_factory=dict)


FIVE_LINE_DEFINITIONS: tuple[FiveLineDefinition, ...] = (
    FiveLineDefinition(
        line_id=FiveLineId.OPS_ACQUISITION,
        name="获客线",
        subtitle="公域引流 → 企业商机 → 合同交付 → 签收对账",
        step_ids=("O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9", "O10"),
        baseline_automation_rate=82.0,
    ),
    FiveLineDefinition(
        line_id=FiveLineId.OPS_PARTNER,
        name="伙伴合作线",
        subtitle="投资方生态产品 · 联合 catalog · 只读进度（预留）",
        step_ids=("B1", "B2", "B3", "B4", "B5"),
        baseline_automation_rate=15.0,
    ),
    FiveLineDefinition(
        line_id=FiveLineId.PROD_WEB,
        name="网站制作维护线",
        subtitle="xiu-ci.com 全站 monorepo · /market/workbench/home 中枢",
        step_ids=("P1",),
        baseline_automation_rate=95.0,
    ),
    FiveLineDefinition(
        line_id=FiveLineId.PROD_MOD,
        name="用户 Mod 制作维护线",
        subtitle="Craft 13 步 · catalog · Mod OTA",
        step_ids=("P2", "P6"),
        baseline_automation_rate=86.0,
    ),
    FiveLineDefinition(
        line_id=FiveLineId.PROD_SOFTWARE,
        name="通用软件线",
        subtitle="2 SKU · Win / macOS / Android / iOS 四发布渠道",
        step_ids=("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"),
        baseline_automation_rate=68.0,
        release_channels=("windows", "macos", "android", "ios"),
        channel_notes={
            "windows": "release-desktop.yml",
            "macos": "release-desktop.yml + notarize.cjs",
            "android": "ci-mobile-android.yml + release-android.yml",
            "ios": "planned — App Store 工程待建",
        },
    ),
    FiveLineDefinition(
        line_id=FiveLineId.SHARED_RETENTION,
        name="归档清理线",
        subtitle="TTL 清理 · 提交门禁 · legacy 归档 · XCMAX 未归类目录",
        step_ids=("P8",),
        baseline_automation_rate=78.0,
    ),
)

# Docker/K8s/SaaS 自托管：开发/内测/运维用，不计入 P-S 四发布渠道
NON_RELEASE_DEPLOY_TARGETS: tuple[str, ...] = ("docker", "k8s", "saas_self_hosted")


def _step_status_map(pipeline: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for block in ("production_line", "operations_line"):
        for s in pipeline.get(block, {}).get("steps", []):
            out[str(s.get("step_id"))] = str(s.get("status", "pending"))
    return out


def get_five_line_status() -> Dict[str, Any]:
    """五线独立自动化率 + 步骤映射（baseline 与实时 completed 取较大展示值）。"""
    pipeline = get_production_line_orchestrator().get_pipeline_status()
    statuses = _step_status_map(pipeline)
    lines: List[Dict[str, Any]] = []

    for defn in FIVE_LINE_DEFINITIONS:
        mapped = [sid for sid in defn.step_ids if sid in statuses]
        completed = sum(1 for sid in mapped if statuses[sid] == "completed")
        live_rate = (
            round(completed / len(mapped) * 100, 1) if mapped else defn.baseline_automation_rate
        )
        display_rate = (
            max(live_rate, defn.baseline_automation_rate)
            if mapped
            else defn.baseline_automation_rate
        )

        entry: Dict[str, Any] = {
            "line_id": defn.line_id.value,
            "name": defn.name,
            "subtitle": defn.subtitle,
            "step_ids": list(defn.step_ids),
            "steps_completed": completed,
            "steps_total": len(mapped),
            "automation_rate": display_rate,
            "live_automation_rate": live_rate,
            "baseline_automation_rate": defn.baseline_automation_rate,
        }
        if defn.release_channels:
            entry["release_channels"] = list(defn.release_channels)
            entry["channel_notes"] = dict(defn.channel_notes)
            entry["non_release_targets"] = list(NON_RELEASE_DEPLOY_TARGETS)
        lines.append(entry)

    rates = [ln["automation_rate"] for ln in lines]
    return {
        "schema_version": 1,
        "lines": lines,
        "overall_automation_rate": round(sum(rates) / len(rates), 1) if rates else 0.0,
        "legacy": {
            "production_line": pipeline.get("production_line"),
            "operations_line": pipeline.get("operations_line"),
        },
    }


_orchestrator: Optional[ProductionLineOrchestrator] = None


def get_production_line_orchestrator() -> ProductionLineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProductionLineOrchestrator()
    return _orchestrator


async def run_production_line_steps(
    step_ids: Sequence[str],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    orch = get_production_line_orchestrator()
    return await orch.run_pipeline_steps(step_ids, context=context)


async def run_production_line(
    line: str = "production",
    start_from: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    orch = get_production_line_orchestrator()
    lt = LineType.PRODUCTION if line == "production" else LineType.OPERATIONS
    return await orch.run_full_pipeline(line=lt, start_from=start_from, context=context)


async def approve_production_line_step(step_id: str, admin_user_id: int = 0) -> StepResult:
    orch = get_production_line_orchestrator()
    return await orch.approve_step(step_id, admin_user_id=admin_user_id)


async def reject_production_line_step(
    step_id: str, admin_user_id: int = 0, reason: str = ""
) -> StepResult:
    orch = get_production_line_orchestrator()
    return await orch.reject_step(step_id, admin_user_id=admin_user_id, reason=reason)


def get_production_line_status() -> Dict[str, Any]:
    orch = get_production_line_orchestrator()
    return orch.get_pipeline_status()
