# ruff: noqa: E402, F401, I001
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
from modstore_server.production_line_orchestrator_part01 import (
    StepStatus as StepStatus,
    ApprovalGate as ApprovalGate,
    LineType as LineType,
    FiveLineId as FiveLineId,
    FlowStep as FlowStep,
)

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
        sub_steps=["ACCEPTANCE_GOVERNANCE + deliverable_smoke", "客户UAT签收(待补齐)"],
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
from modstore_server.production_line_orchestrator_part02 import (
    _bind_step_executors as _bind_step_executors,
)

PRODUCTION_LINE_STEPS = _bind_step_executors(PRODUCTION_LINE_STEPS)
OPERATIONS_LINE_STEPS = _bind_step_executors(OPERATIONS_LINE_STEPS)
PARTNER_LINE_STEPS = _bind_step_executors(PARTNER_LINE_STEPS)
ALL_STEPS: List[FlowStep] = PRODUCTION_LINE_STEPS + OPERATIONS_LINE_STEPS + PARTNER_LINE_STEPS
from modstore_server.production_line_orchestrator_part03 import StepResult as StepResult
from modstore_server.production_line_orchestrator_productionlineorchestrator_mixin01 import (
    _ProductionLineOrchestratorPart01Mixin,
)
from modstore_server.production_line_orchestrator_part04 import (
    ProductionLineOrchestrator as ProductionLineOrchestrator,
    FiveLineDefinition as FiveLineDefinition,
)

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
        subtitle="Win / macOS / Flutter Android / Flutter iOS 四发布渠道",
        step_ids=("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"),
        baseline_automation_rate=68.0,
        release_channels=("windows", "macos", "android", "ios"),
        channel_notes={
            "windows": "release-desktop.yml",
            "macos": "release-desktop.yml + notarize.cjs",
            "android": "ci-mobile-flutter.yml + release-android.yml",
            "ios": "ci-mobile-flutter.yml + release-ios.yml",
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
NON_RELEASE_DEPLOY_TARGETS: tuple[str, ...] = ("docker", "k8s", "saas_self_hosted")
from modstore_server.production_line_orchestrator_part05 import (
    _step_status_map as _step_status_map,
    get_five_line_status as get_five_line_status,
)

_orchestrator: Optional[ProductionLineOrchestrator] = None
from modstore_server.production_line_orchestrator_part06 import (
    get_production_line_orchestrator as get_production_line_orchestrator,
    run_production_line_steps as run_production_line_steps,
    run_production_line as run_production_line,
    approve_production_line_step as approve_production_line_step,
    reject_production_line_step as reject_production_line_step,
    get_production_line_status as get_production_line_status,
)
