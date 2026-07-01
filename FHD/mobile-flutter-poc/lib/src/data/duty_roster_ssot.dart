// CI SSOT: generated from FHD/config/duty_roster.json + mods/_employees/*/manifest.json — DO NOT EDIT BY HAND

import '../models/conversation.dart';

class DutyRosterEmployee {
  const DutyRosterEmployee({
    required this.id,
    required this.label,
    required this.summary,
  });

  final String id;
  final String label;
  final String summary;
}

const adminDutyModId = 'admin-duty-employees';
const plannedAdminEmployeeCount = 55;

const adminDutyRosterEmployees = <DutyRosterEmployee>[
  DutyRosterEmployee(
    id: 'user-customer-service-officer',
    label: '客户客服',
    summary: '查看并回复企业客户的客服消息',
  ),
  DutyRosterEmployee(
    id: 'site-content-editor',
    label: '静态站内容编辑员',
    summary: '维护 xiu-ci.com 营销静态页面的内容、文案、图片引用与数据 JSON；不涉及服务器配置或后端逻辑。',
  ),
  DutyRosterEmployee(
    id: 'seo-sitemap-curator',
    label: 'SEO 站点地图管理员',
    summary:
        '维护 xiu-ci.com 的 SEO 资产：sitemap.xml、robots.txt、百度/必应站长校验文件与结构化数据，确保收录与排名质量。',
  ),
  DutyRosterEmployee(
    id: 'flask-entry-keeper',
    label: 'Flask 入口维护员',
    summary:
        '维护根目录 Flask 应用 app.py 的路由、表单处理、excel-to-ai 动态页与依赖 requirements.txt；对接静态站，不涉及 MODstore 或 Nginx 配置。',
  ),
  DutyRosterEmployee(
    id: 'marketing-site-builder',
    label: '营销站点构建员',
    summary:
        '维护 marketing-site/ Nunjucks 模板与构建脚本（build.mjs、package.json）；与根静态站 site-content-editor 分工：本岗只管独立营销站子项目，不碰 MODstore 与市场 Vue 源码。',
  ),
  DutyRosterEmployee(
    id: 'nginx-config-engineer',
    label: 'Nginx 配置工程师',
    summary: '维护 xiu-ci.com 所有 Nginx 配置文件，包含虚拟主机、TLS、反代规则；不碰任何业务代码。',
  ),
  DutyRosterEmployee(
    id: 'push-update-context-officer',
    label: '推送更新员工',
    summary: '在合并、推送与发布前汇总当前 Git 状态与设备/部署档位；不直接执行生产发布，不修改业务源码。',
  ),
  DutyRosterEmployee(
    id: 'deploy-release-officer',
    label: '发布部署主管',
    summary: '编排 xiu-ci.com 全站的构建与发布流程，包含 Docker 镜像、腾讯云 Pages 部署、脚本维护；不写业务逻辑。',
  ),
  DutyRosterEmployee(
    id: 'security-secrets-guard',
    label: '安全密钥守卫',
    summary:
        '保护 xiu-ci.com 所有密钥、证书与敏感配置；进行依赖 CVE 扫描、CSP/Headers 审计；发现问题时告警，不自动修改生产配置。',
  ),
  DutyRosterEmployee(
    id: 'log-monitor-incident',
    label: '日志监控与事故响应员',
    summary: '归并和分析 xiu-ci.com 所有运行日志、测试报告与覆盖率数据；生成告警摘要并推动事故处置；不修改源码。',
  ),
  DutyRosterEmployee(
    id: 'retention-officer',
    label: '档案清理员',
    summary:
        '周期性清理 workbench_script_runs、上传分片、旋转日志、知识缓存等过期文件，并把每次清理结果写回员工执行流水，作为「定时档案清理」岗位在员工大会上发言。',
  ),
  DutyRosterEmployee(
    id: 'dbops-engineer',
    label: '数据库运维工程师',
    summary:
        '负责 ORM 模型与 Alembic 迁移、慢查询/索引/复制状态诊断、备份恢复策略与权限审计；唯一拥有 models.py / alembic / migrations 写权限的员工，所有 schema 变更必须由本岗发起或评审。',
  ),
  DutyRosterEmployee(
    id: 'llm-ops-engineer',
    label: 'LLM 运维工程师',
    summary:
        '负责 LLM API key 健康检查与轮换建议、token 用量计量与成本追踪、模型选型与路由策略、provider 故障切换建议、便宜/免费 LLM 调研；维护 app/infrastructure/llm/ 与 mod_employee_llm.py；只读 .env 不直接改 key（key 轮换经 admin 审批，与 security-secrets-guard 协作）。',
  ),
  DutyRosterEmployee(
    id: 'legacy-archive-curator',
    label: '工作区归档管理员',
    summary:
        'S-R R3 工作区与 legacy 归档：_archive/、FHD/.archive/、LEGACY_CLEANUP_TRACKING、xcmax-tree 排除项治理。',
  ),
  DutyRosterEmployee(
    id: 'modstore-backend-api',
    label: 'MODstore 后端 API 员',
    summary:
        '维护 MODstore 平台的 Flask 蓝图 API：工作台、市场目录、工作流、LLM 代理与 WebSocket 实时通道；不触碰前端 Vue 文件。',
  ),
  DutyRosterEmployee(
    id: 'employee-pack-curator',
    label: '员工包策展员',
    summary:
        '管理 MODstore 员工包的完整生命周期：AI scaffold、Skill 注册、executor 维护、.xcemp 导入导出与 ESkill 演化固化；不得修改支付模块。',
  ),
  DutyRosterEmployee(
    id: 'payment-billing-reconciler',
    label: '支付账单对账员',
    summary: '维护 MODstore 支付与账单模块：支付宝接口、订单管理、LLM 计费与订阅续费；对账只读为主，禁止直接写生产 DB。',
  ),
  DutyRosterEmployee(
    id: 'java-payment-bridge-officer',
    label: 'Java 支付桥接员',
    summary:
        'P-W MODstore Java 支付面：PaymentController、OrderService、PAYMENT_CONTRACT 与 Python 代理对齐。',
  ),
  DutyRosterEmployee(
    id: 'market-frontend-dev',
    label: '市场前端开发员',
    summary:
        '维护 MODstore 市场前端（非工作台视图）：路由视图、API 对接层、Pinia store、HTTP client；严格遵守 Vue 3 Only，禁止引入 React。',
  ),
  DutyRosterEmployee(
    id: 'workbench-ux-stylist',
    label: '工作台 UX 设计员',
    summary:
        '专注维护 MODstore 工作台（Workbench）的 UX 与交互：画布、右侧边栏、工作台 Shell、AI 草稿审核组件与整体暗色设计系统；严格遵守 Vue 3 Only。',
  ),
  DutyRosterEmployee(
    id: 'fhd-core-maintainer',
    label: 'FHD 核心应用维护员',
    summary:
        '维护 FHD 宿主核心 app/ 与 tests/：应用服务、路由、NeuroBus 集成；产出经 CR Git 管线提交 PR，由 FHD test.yml 与 ci-auto-merge 门控。',
  ),
  DutyRosterEmployee(
    id: 'vibe-coding-maintainer',
    label: 'Vibe-Coding 维护员',
    summary:
        '全权维护 vibe-coding 平台核心库（代码工厂、工作流工厂、自然语言解析、运行时校验器、Agent 层、安全模块）、配套测试、文档、示例代码；为 employee-pack-curator 提供稳定的 vibe_eskill_adapter 接口。',
  ),
  DutyRosterEmployee(
    id: 'mods-and-eskill-curator',
    label: 'Mods/ESkill 策展员',
    summary:
        '管理 mods/ 目录中的 Mod 包与 eskill-prototype/ 原型；负责 .xcemp 上架审核流程与 ESkill 标准文档维护；所有上线须经 CI 审批，不直接操作生产 DB。',
  ),
  DutyRosterEmployee(
    id: 'change-request-auditor',
    label: '变更评审员',
    summary:
        '对员工提交到「待邮件审批」队列的补丁/PR 做自动评审：跑测试 → 静态规则审 → 自动放行低风险 / 升级高风险给 admin；不直接改业务源码、不直接合并到主干。',
  ),
  DutyRosterEmployee(
    id: 'daily-orchestrator',
    label: '每日编排员',
    summary:
        '每日编排员工包：实际执行由宿主 daily_orchestrator_job 注入 agent_runner 后完成；员工包本身只提供 echo / llm_md / webhook / agent 通用 handler。',
  ),
  DutyRosterEmployee(
    id: 'intake-dispatcher',
    label: '需求接入员',
    summary:
        '把外部输入（admin 自然语言下达、邮件、微信、客服工单、`mianshi/` 候补包、外部 webhook）规整成结构化 task，写入「待派发」队列；本岗只做语义解析与归一化，不直接选员工、不直接改业务代码。',
  ),
  DutyRosterEmployee(
    id: 'task-router-officer',
    label: '任务派发员',
    summary:
        '把 `intake-dispatcher` 产出的结构化 task 派发给最合适的员工：基于 task.files_hint 与各员工 scope_globs 做匹配，命中多人时按仲裁规则选一人，无人匹配则升级 admin；本岗只做路由决策，不直接改业务代码、不执行任务。',
  ),
  DutyRosterEmployee(
    id: 'github-pr-gatekeeper',
    label: 'GitHub PR 守门员',
    summary:
        '通用 GitHub PR 审查：Dependabot/Renovate PR 自动审查与合并、CI 状态聚合、低风险自动 approve、major 版本升级派发 vibe-coding-maintainer 验证。与 change-request-auditor 分工：本员工专注 GitHub 原生 PR（外部），change-request-auditor 专注员工包补丁队列（内部 CR）。',
  ),
  DutyRosterEmployee(
    id: 'enterprise-adoption-officer',
    label: '企业使用跟踪员',
    summary:
        '跟踪 O6 企业使用阶段：租户激活、功能采纳、用量遥测与回访触发；与 user-customer-service-officer 分工（本岗偏数据与里程碑，客服偏交互）。',
  ),
  DutyRosterEmployee(
    id: 'delivery-receipt-officer',
    label: '交付签收员',
    summary:
        'O8 里程碑签收与交付确认：对接 OPS_CLOSURE、签收工单、test-qa-runner 门禁与 receipt 工作流。',
  ),
  DutyRosterEmployee(
    id: 'mobile-android-release-officer',
    label: 'Android 发版员',
    summary:
        'P-S Android 渠道构建与发布：ci-mobile-android.yml、release-android.yml、APK/AAB 产出与 smoke。',
  ),
  DutyRosterEmployee(
    id: 'mobile-harmony-release-officer',
    label: '鸿蒙发版员',
    summary:
        '鸿蒙 HarmonyOS 渠道全自动发版:assembleApp 编译 → hap-sign-tool 真证书签名(AGC 发布证书)→ AGC Publishing API 上传 + 自动提交审核。本机(Mac mini)执行,密钥在 ~/XCMAX-runtime/harmony/signing(仓库外);一条龙 scripts/release-harmony.sh,详见 RUNBOOK.md。',
  ),
  DutyRosterEmployee(
    id: 'mobile-ios-release-officer',
    label: 'iOS 发版员',
    summary:
        'XCAGI iOS 渠道发布：主线上架、冻结兼容 SKU、Apple Developer profile、GitHub Secrets、XcodeGen 工程、签名、TestFlight / App Store Connect 上传与 release 门禁。',
  ),
  DutyRosterEmployee(
    id: 'test-qa-runner',
    label: '测试质量运行员',
    summary:
        '负责全站测试套件的维护与执行：pytest 单元/集成测试、vitest 前端单测、Playwright E2E 测试、pre-commit hooks、覆盖率门禁、CI 工作流测试步骤、TypeScript 类型检查；输出测试结果并推动覆盖率达标；不修改被测源码。',
  ),
  DutyRosterEmployee(
    id: 'doc-knowledge-curator',
    label: '文档知识管理员',
    summary:
        '维护 xiu-ci.com 与 MODstore 平台的全部文档资产：README、ESkill.md、docs/ 目录、需求/方案 Markdown，以及 yuangon/ 各员工 README 同步；可调用 py-doc-generator.xcemp 与 project-doc-generator.xcemp 辅助生成文档；不修改源码。员工包专属文档（fhd-employee-composition.md、员工制作增强设计方案.md、employee_publish_wizard.md、0003-artifacts-bundles-employee-packs.md）由 employee-pack-curator 全权负责，本员工不主动修改。',
  ),
  DutyRosterEmployee(
    id: 'employee-interview-assistant',
    label: '员工信息访谈员',
    summary:
        '面向内部编制与协作场景：通过结构化提问与表单补全，帮助其他员工（及岗位包）补全元数据、能力说明、\n运行依赖与风险字段；不替代 HR 正式录用流程，不存储敏感个人身份信息于未授权位置。',
  ),
  DutyRosterEmployee(
    id: 'employee-pack-quality-interviewer',
    label: '员工包质询员',
    summary:
        '对候选 employee_pack（.xcemp）做结构化「入职面试」：基于用户粘贴的 manifest 节选、同步测试日志或\n沙盒 JSON，对照职责边界与平台契约给出录用/有条件录用/驳回结论与可执行修改清单。\n不替代渗透测试、法务合规或正式 HR 录用；不编造未出现在输入中的文件路径、接口或密钥。',
  ),
  DutyRosterEmployee(
    id: 'intent-analyst',
    label: '需求分析员工',
    summary: '解析用户自然语言需求，提取结构化意图、领域关键词与建议能力；识别用户身份与权限',
  ),
  DutyRosterEmployee(
    id: 'employee-planner',
    label: '规划设计员工',
    summary: '根据结构化需求规划员工包架构，拆分员工职责、脚本工作流与 Skill 组；输出一站式员工蓝图',
  ),
  DutyRosterEmployee(
    id: 'artifact-generator',
    label: '产物生成员工',
    summary: '根据规划蓝图生成员工包产物（manifest、Python 实现、资产文件）；支持 LLM 驱动和资产驱动两种模式',
  ),
  DutyRosterEmployee(
    id: 'quality-validator',
    label: '质检员工',
    summary: '对生成的产物进行服务端校验，包括 manifest 合规性、Python 语法、资产完整性与一致性检查',
  ),
  DutyRosterEmployee(
    id: 'miniapp-builder',
    label: '小程序员工',
    summary: '为员工包生成配套脚本工作流（小程序），将自然语言需求转化为可执行的脚本逻辑',
  ),
  DutyRosterEmployee(
    id: 'script-binder',
    label: '配置绑定员工',
    summary: '将生成的脚本工作流嵌入员工包，更新 manifest 能力声明与目录结构',
  ),
  DutyRosterEmployee(
    id: 'workflow-automator',
    label: '流程自动化员工',
    summary: '为员工包创建自动化工作流（Skill 组），通过自然语言生成画布节点与连线',
  ),
  DutyRosterEmployee(
    id: 'pack-registrar',
    label: '打包登记员工',
    summary: '将员工包登记到 Catalog 目录，执行五维审核，生成 .xcemp 发布包',
  ),
  DutyRosterEmployee(
    id: 'sandbox-tester',
    label: '测试员工',
    summary: '对员工工作流执行沙箱测试，包括结构校验与 Mock 执行验证',
  ),
  DutyRosterEmployee(
    id: 'code-validator',
    label: '代码校验员工',
    summary: '对员工包体进行轻量校验，包括 manifest 合规性、Python 编译检查、包体一致性、独立可执行验证',
  ),
  DutyRosterEmployee(
    id: 'self-checker',
    label: '自检员工',
    summary: '执行员工包独立可执行自检，验证 .xcemp 包在隔离环境下可正常加载与运行',
  ),
  DutyRosterEmployee(
    id: 'host-checker',
    label: '运维员工',
    summary: '探测宿主环境连通性，验证 LLM 密钥状态、API 版本兼容性与服务可达性',
  ),
  DutyRosterEmployee(
    id: 'hex-quality-assessor',
    label: '六维质检员工',
    summary: '对制作车间产物执行六维质量评估与放行建议',
  ),
  DutyRosterEmployee(
    id: 'ecosystem-partner-onboard-officer',
    label: '生态伙伴接入员',
    summary: 'O-B B1 生态伙伴 onboarding · 租户隔离 · 联合 SSO 与伙伴档案建档。',
  ),
  DutyRosterEmployee(
    id: 'ecosystem-joint-catalog-officer',
    label: '联合 Catalog 策展员',
    summary: 'O-B B2 生态联合 SKU · MODstore catalog 扩展 · 伙伴商品挂载与可见性策略。',
  ),
  DutyRosterEmployee(
    id: 'ecosystem-delivery-reporter',
    label: '生态交付回传员',
    summary: 'O-B B3 联合包交付遥测 · 里程碑回写 O-A CRM 快照 · 生态进度事件。',
  ),
  DutyRosterEmployee(
    id: 'ecosystem-investor-portal-officer',
    label: '投资方只读门户员',
    summary: 'O-B B4 投资方/伙伴只读 Portal · 里程碑与风险视图 · 进度只读 API。',
  ),
  DutyRosterEmployee(
    id: 'ecosystem-revenue-share-reconciler',
    label: '生态分润对账员',
    summary:
        'O-B B5 渠道分润 · 联合 GMV 对账 · 与 payment-billing-reconciler 分工（本岗偏伙伴分润）。',
  ),
];

List<ConversationItem> adminDutyRosterConversationItems() {
  return adminDutyRosterEmployees.map((employee) {
    return ConversationItem(
      id: 'employee:$adminDutyModId:${employee.id}',
      type: ConversationType.aiTask,
      title: employee.label,
      subtitle: employee.summary,
      timestampText: '',
    );
  }).toList(growable: false);
}
