// CI SSOT: generated from FHD/config/duty_roster.json + mods/_employees/*/manifest.json — DO NOT EDIT BY HAND
/**
 * 编制矩阵（CI SSOT 生成，禁止人手修改）。
 * 来源：FHD/config/duty_roster.json + mods/_employees 下各 manifest.json
 * 生成命令：python scripts/dev/sync_duty_roster.py --generate --target frontend
 */

/**
 * 编制区域（与 FHD config/duty_roster.json areas 块一致）。
 */
export const YUANGON_AREAS: Record<string, { label: string; ids: string[] }> = {
  'site-and-marketing': {
    label: '对外网站与 SEO',
    ids: [
      'site-content-editor',
      'seo-sitemap-curator',
      'flask-entry-keeper',
      'marketing-site-builder',
    ],
  },
  'server-and-ops': {
    label: '服务器与运维',
    ids: [
      'nginx-config-engineer',
      'push-update-context-officer',
      'deploy-release-officer',
      'security-secrets-guard',
      'log-monitor-incident',
      'retention-officer',
      'dbops-engineer',
      'llm-ops-engineer',
      'legacy-archive-curator',
    ],
  },
  'modstore-backend': {
    label: 'MODstore 后端',
    ids: [
      'modstore-backend-api',
      'employee-pack-curator',
      'payment-billing-reconciler',
      'java-payment-bridge-officer',
    ],
  },
  'modstore-frontend': {
    label: 'MODstore 前端',
    ids: [
      'market-frontend-dev',
      'workbench-ux-stylist',
    ],
  },
  'platform-core': {
    label: '平台核心',
    ids: [
      'fhd-core-maintainer',
      'vibe-coding-maintainer',
      'mods-and-eskill-curator',
      'change-request-auditor',
      'github-pr-gatekeeper',
      'daily-orchestrator',
      'intake-dispatcher',
      'task-router-officer',
      'user-customer-service-officer',
      'enterprise-adoption-officer',
      'delivery-receipt-officer',
      'mobile-android-release-officer',
      'mobile-harmony-release-officer',
      'mobile-ios-release-officer',
    ],
  },
  'quality-and-docs': {
    label: '质量与文档',
    ids: [
      'test-qa-runner',
      'doc-knowledge-curator',
      'employee-interview-assistant',
      'employee-pack-quality-interviewer',
    ],
  },
  'craft-workshop': {
    label: '制作车间',
    ids: [
      'intent-analyst',
      'employee-planner',
      'artifact-generator',
      'quality-validator',
      'miniapp-builder',
      'script-binder',
      'workflow-automator',
      'pack-registrar',
      'sandbox-tester',
      'code-validator',
      'self-checker',
      'host-checker',
      'hex-quality-assessor',
    ],
  },
  'partner-ecosystem': {
    label: '生态伙伴 O-B',
    ids: [
      'ecosystem-partner-onboard-officer',
      'ecosystem-joint-catalog-officer',
      'ecosystem-delivery-reporter',
      'ecosystem-investor-portal-officer',
      'ecosystem-revenue-share-reconciler',
    ],
  },
}

/** 编制内全部员工包 ID（从 YUANGON_AREAS 聚合，用于工作台过滤与删除保护）。 */
export const ALL_PLANNED_YUANGON_PKG_IDS: ReadonlySet<string> = new Set(
  (Object.values(YUANGON_AREAS) as { ids: string[] }[]).flatMap((b) => b.ids),
)

/**
 * 编制员工中文名（来源于 mods/_employees 下各 manifest.json 的 name 字段）。
 */
export const YUANGON_PKG_ROLE_LABELS: Record<string, string> = {
  'artifact-generator': '产物生成员工',
  'change-request-auditor': '变更评审员',
  'code-validator': '代码校验员工',
  'daily-orchestrator': '每日编排员',
  'dbops-engineer': '数据库运维工程师',
  'delivery-receipt-officer': '交付签收员',
  'deploy-release-officer': '发布部署主管',
  'doc-knowledge-curator': '文档知识管理员',
  'ecosystem-delivery-reporter': '生态交付回传员',
  'ecosystem-investor-portal-officer': '投资方只读门户员',
  'ecosystem-joint-catalog-officer': '联合 Catalog 策展员',
  'ecosystem-partner-onboard-officer': '生态伙伴接入员',
  'ecosystem-revenue-share-reconciler': '生态分润对账员',
  'employee-interview-assistant': '员工信息访谈员',
  'employee-pack-curator': '员工包策展员',
  'employee-pack-quality-interviewer': '员工包质询员',
  'employee-planner': '规划设计员工',
  'enterprise-adoption-officer': '企业使用跟踪员',
  'fhd-core-maintainer': 'FHD 核心应用维护员',
  'flask-entry-keeper': 'Flask 入口维护员',
  'github-pr-gatekeeper': 'GitHub PR 守门员',
  'hex-quality-assessor': '六维质检员工',
  'host-checker': '运维员工',
  'intake-dispatcher': '需求接入员',
  'intent-analyst': '需求分析员工',
  'java-payment-bridge-officer': 'Java 支付桥接员',
  'legacy-archive-curator': '工作区归档管理员',
  'llm-ops-engineer': 'LLM 运维工程师',
  'log-monitor-incident': '日志监控与事故响应员',
  'market-frontend-dev': '市场前端开发员',
  'marketing-site-builder': '营销站点构建员',
  'miniapp-builder': '小程序员工',
  'mobile-android-release-officer': 'Android 发版员',
  'mobile-harmony-release-officer': '鸿蒙发版员',
  'mobile-ios-release-officer': 'iOS 发版员',
  'mods-and-eskill-curator': 'Mods/ESkill 策展员',
  'modstore-backend-api': 'MODstore 后端 API 员',
  'nginx-config-engineer': 'Nginx 配置工程师',
  'pack-registrar': '打包登记员工',
  'payment-billing-reconciler': '支付账单对账员',
  'push-update-context-officer': '推送更新员工',
  'quality-validator': '质检员工',
  'retention-officer': '档案清理员',
  'sandbox-tester': '测试员工',
  'script-binder': '配置绑定员工',
  'security-secrets-guard': '安全密钥守卫',
  'self-checker': '自检员工',
  'seo-sitemap-curator': 'SEO 站点地图管理员',
  'site-content-editor': '静态站内容编辑员',
  'task-router-officer': '任务派发员',
  'test-qa-runner': '测试质量运行员',
  'user-customer-service-officer': '用户客服员工',
  'vibe-coding-maintainer': 'Vibe-Coding 维护员',
  'workbench-ux-stylist': '工作台 UX 设计员',
  'workflow-automator': '流程自动化员工',
}

/**
 * 编制员工说明（来源于 mods/_employees 下各 manifest.json 的 description 字段）。
 */
export const YUANGON_PKG_DESCRIPTIONS: Record<string, string> = {
  'artifact-generator': '根据规划蓝图生成员工包产物（manifest、Python 实现、资产文件）；支持 LLM 驱动和资产驱动两种模式',
  'change-request-auditor': '对员工提交到「待邮件审批」队列的补丁/PR 做自动评审：跑测试 → 静态规则审 → 自动放行低风险 / 升级高风险给 admin；不直接改业务源码、不直接合并到主干。',
  'code-validator': '对员工包体进行轻量校验，包括 manifest 合规性、Python 编译检查、包体一致性、独立可执行验证',
  'daily-orchestrator': '每日编排员工包：实际执行由宿主 daily_orchestrator_job 注入 agent_runner 后完成；员工包本身只提供 echo / llm_md / webhook / agent 通用 handler。',
  'dbops-engineer': '负责 ORM 模型与 Alembic 迁移、慢查询/索引/复制状态诊断、备份恢复策略与权限审计；唯一拥有 models.py / alembic / migrations 写权限的员工，所有 schema 变更必须由本岗发起或评审。',
  'delivery-receipt-officer': 'O8 里程碑签收与交付确认：对接 OPS_CLOSURE、签收工单、test-qa-runner 门禁与 receipt 工作流。',
  'deploy-release-officer': '编排 xiu-ci.com 全站的构建与发布流程，包含 Docker 镜像、腾讯云 Pages 部署、脚本维护；不写业务逻辑。',
  'doc-knowledge-curator': '维护 xiu-ci.com 与 MODstore 平台的全部文档资产：README、ESkill.md、docs/ 目录、需求/方案 Markdown，以及 yuangon/ 各员工 README 同步；可调用 py-doc-generator.xcemp 与 project-doc-generator.xcemp 辅助生成文档；不修改源码。员工包专属文档（fhd-employee-composition.md、员工制作增强设计方案.md、employee_publish_wizard.md、0003-artifacts-bundles-employee-packs.md）由 employee-pack-curator 全权负责，本员工不主动修改。',
  'ecosystem-delivery-reporter': 'O-B B3 联合包交付遥测 · 里程碑回写 O-A CRM 快照 · 生态进度事件。',
  'ecosystem-investor-portal-officer': 'O-B B4 投资方/伙伴只读 Portal · 里程碑与风险视图 · 进度只读 API。',
  'ecosystem-joint-catalog-officer': 'O-B B2 生态联合 SKU · MODstore catalog 扩展 · 伙伴商品挂载与可见性策略。',
  'ecosystem-partner-onboard-officer': 'O-B B1 生态伙伴 onboarding · 租户隔离 · 联合 SSO 与伙伴档案建档。',
  'ecosystem-revenue-share-reconciler': 'O-B B5 渠道分润 · 联合 GMV 对账 · 与 payment-billing-reconciler 分工（本岗偏伙伴分润）。',
  'employee-interview-assistant': '面向内部编制与协作场景：通过结构化提问与表单补全，帮助其他员工（及岗位包）补全元数据、能力说明、\n运行依赖与风险字段；不替代 HR 正式录用流程，不存储敏感个人身份信息于未授权位置。',
  'employee-pack-curator': '管理 MODstore 员工包的完整生命周期：AI scaffold、Skill 注册、executor 维护、.xcemp 导入导出与 ESkill 演化固化；不得修改支付模块。',
  'employee-pack-quality-interviewer': '对候选 employee_pack（.xcemp）做结构化「入职面试」：基于用户粘贴的 manifest 节选、同步测试日志或\n沙盒 JSON，对照职责边界与平台契约给出录用/有条件录用/驳回结论与可执行修改清单。\n不替代渗透测试、法务合规或正式 HR 录用；不编造未出现在输入中的文件路径、接口或密钥。',
  'employee-planner': '根据结构化需求规划员工包架构，拆分员工职责、脚本工作流与 Skill 组；输出一站式员工蓝图',
  'enterprise-adoption-officer': '跟踪 O6 企业使用阶段：租户激活、功能采纳、用量遥测与回访触发；与 user-customer-service-officer 分工（本岗偏数据与里程碑，客服偏交互）。',
  'fhd-core-maintainer': '维护 FHD 宿主核心 app/ 与 tests/：应用服务、路由、NeuroBus 集成；产出经 CR Git 管线提交 PR，由 FHD test.yml 与 ci-auto-merge 门控。',
  'flask-entry-keeper': '维护根目录 Flask 应用 app.py 的路由、表单处理、excel-to-ai 动态页与依赖 requirements.txt；对接静态站，不涉及 MODstore 或 Nginx 配置。',
  'github-pr-gatekeeper': '通用 GitHub PR 审查：Dependabot/Renovate PR 自动审查与合并、CI 状态聚合、低风险自动 approve、major 版本升级派发 vibe-coding-maintainer 验证。与 change-request-auditor 分工：本员工专注 GitHub 原生 PR（外部），change-request-auditor 专注员工包补丁队列（内部 CR）。',
  'hex-quality-assessor': '对制作车间产物执行六维质量评估与放行建议',
  'host-checker': '探测宿主环境连通性，验证 LLM 密钥状态、API 版本兼容性与服务可达性',
  'intake-dispatcher': '把外部输入（admin 自然语言下达、邮件、微信、客服工单、`mianshi/` 候补包、外部 webhook）规整成结构化 task，写入「待派发」队列；本岗只做语义解析与归一化，不直接选员工、不直接改业务代码。',
  'intent-analyst': '解析用户自然语言需求，提取结构化意图、领域关键词与建议能力；识别用户身份与权限',
  'java-payment-bridge-officer': 'P-W MODstore Java 支付面：PaymentController、OrderService、PAYMENT_CONTRACT 与 Python 代理对齐。',
  'legacy-archive-curator': 'S-R R3 工作区与 legacy 归档：_archive/、FHD/.archive/、LEGACY_CLEANUP_TRACKING、xcmax-tree 排除项治理。',
  'llm-ops-engineer': '负责 LLM API key 健康检查与轮换建议、token 用量计量与成本追踪、模型选型与路由策略、provider 故障切换建议、便宜/免费 LLM 调研；维护 app/infrastructure/llm/ 与 mod_employee_llm.py；只读 .env 不直接改 key（key 轮换经 admin 审批，与 security-secrets-guard 协作）。',
  'log-monitor-incident': '归并和分析 xiu-ci.com 所有运行日志、测试报告与覆盖率数据；生成告警摘要并推动事故处置；不修改源码。',
  'market-frontend-dev': '维护 MODstore 市场前端（非工作台视图）：路由视图、API 对接层、Pinia store、HTTP client；严格遵守 Vue 3 Only，禁止引入 React。',
  'marketing-site-builder': '维护 marketing-site/ Nunjucks 模板与构建脚本（build.mjs、package.json）；与根静态站 site-content-editor 分工：本岗只管独立营销站子项目，不碰 MODstore 与市场 Vue 源码。',
  'miniapp-builder': '为员工包生成配套脚本工作流（小程序），将自然语言需求转化为可执行的脚本逻辑',
  'mobile-android-release-officer': 'P-S Android 渠道构建与发布：ci-mobile-android.yml、release-android.yml、APK/AAB 产出与 smoke。',
  'mobile-harmony-release-officer': '鸿蒙 HarmonyOS 渠道全自动发版:assembleApp 编译 → hap-sign-tool 真证书签名(AGC 发布证书)→ AGC Publishing API 上传 + 自动提交审核。本机(Mac mini)执行,密钥在 ~/XCMAX-runtime/harmony/signing(仓库外);一条龙 scripts/release-harmony.sh,详见 RUNBOOK.md。',
  'mobile-ios-release-officer': 'XCAGI iOS 渠道发布：主线上架、冻结兼容 SKU、Apple Developer profile、GitHub Secrets、XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。',
  'mods-and-eskill-curator': '管理 mods/ 目录中的 Mod 包与 eskill-prototype/ 原型；负责 .xcemp 上架审核流程与 ESkill 标准文档维护；所有上线须经 CI 审批，不直接操作生产 DB。',
  'modstore-backend-api': '维护 MODstore 平台的 Flask 蓝图 API：工作台、市场目录、工作流、LLM 代理与 WebSocket 实时通道；不触碰前端 Vue 文件。',
  'nginx-config-engineer': '维护 xiu-ci.com 所有 Nginx 配置文件，包含虚拟主机、TLS、反代规则；不碰任何业务代码。',
  'pack-registrar': '将员工包登记到 Catalog 目录，执行五维审核，生成 .xcemp 发布包',
  'payment-billing-reconciler': '维护 MODstore 支付与账单模块：支付宝接口、订单管理、LLM 计费与订阅续费；对账只读为主，禁止直接写生产 DB。',
  'push-update-context-officer': '在合并、推送与发布前汇总当前 Git 状态与设备/部署档位；不直接执行生产发布，不修改业务源码。',
  'quality-validator': '对生成的产物进行服务端校验，包括 manifest 合规性、Python 语法、资产完整性与一致性检查',
  'retention-officer': '周期性清理 workbench_script_runs、上传分片、旋转日志、知识缓存等过期文件，并把每次清理结果写回员工执行流水，作为「定时档案清理」岗位在员工大会上发言。',
  'sandbox-tester': '对员工工作流执行沙箱测试，包括结构校验与 Mock 执行验证',
  'script-binder': '将生成的脚本工作流嵌入员工包，更新 manifest 能力声明与目录结构',
  'security-secrets-guard': '保护 xiu-ci.com 所有密钥、证书与敏感配置；进行依赖 CVE 扫描、CSP/Headers 审计；发现问题时告警，不自动修改生产配置。',
  'self-checker': '执行员工包独立可执行自检，验证 .xcemp 包在隔离环境下可正常加载与运行',
  'seo-sitemap-curator': '维护 xiu-ci.com 的 SEO 资产：sitemap.xml、robots.txt、百度/必应站长校验文件与结构化数据，确保收录与排名质量。',
  'site-content-editor': '维护 xiu-ci.com 营销静态页面的内容、文案、图片引用与数据 JSON；不涉及服务器配置或后端逻辑。',
  'task-router-officer': '把 `intake-dispatcher` 产出的结构化 task 派发给最合适的员工：基于 task.files_hint 与各员工 scope_globs 做匹配，命中多人时按仲裁规则选一人，无人匹配则升级 admin；本岗只做路由决策，不直接改业务代码、不执行任务。',
  'test-qa-runner': '负责全站测试套件的维护与执行：pytest 单元/集成测试、vitest 前端单测、Playwright E2E 测试、pre-commit hooks、覆盖率门禁、CI 工作流测试步骤、TypeScript 类型检查；输出测试结果并推动覆盖率达标；不修改被测源码。',
  'user-customer-service-officer': '面向终端用户的客服 AI 员工：绑定微信账号资产，在 Mac 本地协助沟通；首要能力为需求采集（询问客户需求并推送表单链接）。',
  'vibe-coding-maintainer': '全权维护 vibe-coding 平台核心库（代码工厂、工作流工厂、自然语言解析、运行时校验器、Agent 层、安全模块）、配套测试、文档、示例代码；为 employee-pack-curator 提供稳定的 vibe_eskill_adapter 接口。',
  'workbench-ux-stylist': '专注维护 MODstore 工作台（Workbench）的 UX 与交互：画布、右侧边栏、工作台 Shell、AI 草稿审核组件与整体暗色设计系统；严格遵守 Vue 3 Only。',
  'workflow-automator': '为员工包创建自动化工作流（Skill 组），通过自然语言生成画布节点与连线',
}

export type DutySubzone = { label: string; ids: string[] }
export type DutyDepartment = {
  label: string
  five_line_id: string
  reserved?: boolean
  subzones: Record<string, DutySubzone>
}

export const SIX_LINE_DEPARTMENTS: Record<string, DutyDepartment> = {
  ops_acquisition: {
    label: 'O-A 获客部',
    five_line_id: 'ops_acquisition',
    subzones: {
      'public-acquisition': { label: '公域获客 O1', ids: [
        'site-content-editor',
        'seo-sitemap-curator',
        'marketing-site-builder',
      ] },
      'crm-pipeline': { label: 'CRM 与商机 O2-O3', ids: [
        'user-customer-service-officer',
        'intake-dispatcher',
        'modstore-backend-api',
      ] },
      'billing': { label: '收费对账 O4/O10', ids: [
        'payment-billing-reconciler',
      ] },
      'delivery-feedback': { label: '交付反馈签收 O5/O7-O8', ids: [
        'deploy-release-officer',
        'change-request-auditor',
        'test-qa-runner',
        'enterprise-adoption-officer',
        'delivery-receipt-officer',
      ] },
    },
  },
  ops_partner: {
    label: 'O-B 伙伴部',
    five_line_id: 'ops_partner',
    subzones: {
      'partner-onboard': { label: '生态接入 B1', ids: [
        'ecosystem-partner-onboard-officer',
      ] },
      'joint-catalog': { label: '联合 catalog B2', ids: [
        'ecosystem-joint-catalog-officer',
      ] },
      'delivery-bridge': { label: '生态交付 B3', ids: [
        'ecosystem-delivery-reporter',
      ] },
      'investor-portal': { label: '投资方视图 B4', ids: [
        'ecosystem-investor-portal-officer',
      ] },
      'revenue-share': { label: '分润对账 B5', ids: [
        'ecosystem-revenue-share-reconciler',
      ] },
    },
  },
  prod_web: {
    label: 'P-W 网站部',
    five_line_id: 'prod_web',
    subzones: {
      'static-site': { label: '营销静态 P1a', ids: [
        'site-content-editor',
        'seo-sitemap-curator',
        'marketing-site-builder',
        'flask-entry-keeper',
      ] },
      'market-spa': { label: '市场 SPA P1b', ids: [
        'market-frontend-dev',
      ] },
      'workbench': { label: '工作台 P1c', ids: [
        'workbench-ux-stylist',
        'daily-orchestrator',
        'task-router-officer',
        'vibe-coding-maintainer',
      ] },
      'modstore-api': { label: 'MODstore 后端 P1d', ids: [
        'modstore-backend-api',
        'employee-pack-curator',
        'java-payment-bridge-officer',
      ] },
      'docs-seo': { label: '文档 SEO P1e', ids: [
        'doc-knowledge-curator',
        'seo-sitemap-curator',
      ] },
      'nginx-deploy': { label: 'nginx 部署 P1f', ids: [
        'nginx-config-engineer',
        'deploy-release-officer',
      ] },
    },
  },
  prod_mod: {
    label: 'P-M Mod 部',
    five_line_id: 'prod_mod',
    subzones: {
      'craft-pipeline': { label: 'Craft 13 步 P2', ids: [
        'intent-analyst',
        'employee-planner',
        'artifact-generator',
        'quality-validator',
        'miniapp-builder',
        'script-binder',
        'workflow-automator',
        'pack-registrar',
        'sandbox-tester',
        'code-validator',
        'self-checker',
        'host-checker',
        'hex-quality-assessor',
      ] },
      'sandbox-catalog': { label: '沙盒 catalog P3', ids: [
        'sandbox-tester',
        'code-validator',
        'self-checker',
        'mods-and-eskill-curator',
        'test-qa-runner',
      ] },
      'mod-ota': { label: 'Mod OTA P6', ids: [
        'push-update-context-officer',
        'pack-registrar',
      ] },
      'roster-quality': { label: '编制质检', ids: [
        'employee-interview-assistant',
        'employee-pack-quality-interviewer',
      ] },
    },
  },
  prod_software: {
    label: 'P-S 软件部',
    five_line_id: 'prod_software',
    subzones: {
      'core-coding': { label: '核心编码 P2', ids: [
        'fhd-core-maintainer',
        'vibe-coding-maintainer',
      ] },
      'testing': { label: '自动测试 P3', ids: [
        'test-qa-runner',
        'sandbox-tester',
        'code-validator',
        'self-checker',
      ] },
      'build-release': { label: '构建发布 P4-P5', ids: [
        'pack-registrar',
        'deploy-release-officer',
        'change-request-auditor',
        'github-pr-gatekeeper',
        'mobile-android-release-officer',
        'mobile-harmony-release-officer',
        'mobile-ios-release-officer',
      ] },
      'ota-monitor': { label: 'OTA 监控 P6-P7', ids: [
        'push-update-context-officer',
        'log-monitor-incident',
        'host-checker',
      ] },
      'orchestration': { label: '编排迭代 P9-P10', ids: [
        'daily-orchestrator',
        'intake-dispatcher',
        'task-router-officer',
        'github-pr-gatekeeper',
        'dbops-engineer',
        'llm-ops-engineer',
      ] },
    },
  },
  shared_retention: {
    label: 'S-R 归档部',
    five_line_id: 'shared_retention',
    subzones: {
      'ttl-janitor': { label: 'TTL 清理 R1', ids: [
        'retention-officer',
      ] },
      'commit-guards': { label: '提交门禁 R2', ids: [
        'security-secrets-guard',
      ] },
      'legacy-archive': { label: 'legacy 归档 R3', ids: [
        'retention-officer',
        'legacy-archive-curator',
      ] },
      'alert-cve': { label: '告警 CVE R4', ids: [
        'log-monitor-incident',
        'daily-orchestrator',
        'security-secrets-guard',
      ] },
    },
  },
}

export const DEPARTMENT_ORDER = [
  'ops_acquisition',
  'ops_partner',
  'prod_web',
  'prod_mod',
  'prod_software',
  'shared_retention',
] as const

export const DEPARTMENT_COLORS: Record<string, string> = {
  ops_acquisition: '#22d3ee',
  ops_partner: '#4ade80',
  prod_web: '#fb923c',
  prod_mod: '#a78bfa',
  prod_software: '#facc15',
  shared_retention: '#79c0ff',
}

export const CRAFT_SUBZONE_ID = 'craft-pipeline'
