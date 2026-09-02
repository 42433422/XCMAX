// ignore_for_file: prefer_single_quotes

part of 'ai_group_snapshot.dart';

const _aiGroupSnapshotDepts1 = <AiGroupConversation>[
  AiGroupConversation(
    id: "506de49aa92342149885f648601ca3f0",
    name: "超级开发部",
    memberCount: 5,
    preview: "小C助理、Codex、Cursor、Claude、Trae 在群里协同处理开发任务。",
    timestampText: "12小时前",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "codex-super-employee",
        name: "超级员工-Codex",
        summary: "Codex CLI 超级员工，支持代码任务、测试和汇报。",
        avatarUrl: null,
        avatarKey: "codex",
      ),
      AiGroupMember(
        employeeId: "cursor-super-employee",
        name: "超级员工-Cursor",
        summary: "Cursor Agent 超级员工，支持工程修改和上下文协作。",
        avatarUrl: null,
        avatarKey: "cursor",
      ),
      AiGroupMember(
        employeeId: "claude-super-employee",
        name: "超级员工-Claude",
        summary: "Claude CLI 超级员工，支持分析、编写和任务复盘。",
        avatarUrl: null,
        avatarKey: "claude",
      ),
      AiGroupMember(
        employeeId: "trae-super-employee",
        name: "超级员工-Trae",
        summary: "Trae CLI 超级员工，支持 IDE 执行端、备用额度和补位协作。",
        avatarUrl: null,
        avatarKey: "trae",
      ),
    ],
  ),
  AiGroupConversation(
    id: "dept:prod_web",
    name: "P-W 网站部",
    memberCount: 11,
    preview: "文档知识管理员：我是文档知识管理员，主要负责维护 xiu-ci.com 与 MODstore 平台的全部文档资产。",
    timestampText: "6/24",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "market-frontend-dev",
        name: "市场前端开发员",
        summary:
            "维护 MODstore 市场前端（非工作台视图）：路由视图、API 对接层、Pinia store、HTTP client；严格遵守 Vue 3 Only，禁止引入 React。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "task-router-officer",
        name: "任务派发员",
        summary:
            "把 `intake-dispatcher` 产出的结构化 task 派发给最合适的员工：基于 task.files_hint 与各员工 scope_globs 做匹配，命中多人时按仲裁规则选一人，无人匹配则升级 admin；本岗只做路由决策，不直接改业务代码、不执行任务。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "doc-knowledge-curator",
        name: "文档知识管理员",
        summary:
            "维护 xiu-ci.com 与 MODstore 平台的全部文档资产：README、ESkill.md、docs/ 目录、需求/方案 Markdown，以及 yuangon/ 各员工 README 同步；可调用 py-doc-generator.xcemp 与 project-doc-generator.xcemp 辅助生成文档；不修改源码。员工包专属文档（fhd-employee-composition.md、员工制作增强设计方案.md、employee_publish_wizard.md、0003-artifacts-bundles-employee",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "vibe-coding-maintainer",
        name: "Vibe-Coding 维护员",
        summary:
            "全权维护 vibe-coding 平台核心库（代码工厂、工作流工厂、自然语言解析、运行时校验器、Agent 层、安全模块）、配套测试、文档、示例代码；为 employee-pack-curator 提供稳定的 vibe_eskill_adapter 接口。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "daily-orchestrator",
        name: "每日编排员",
        summary:
            "每日定时：在独立分支上做最小修复（测试失败、日志告警），提交后进入「待邮件审批」队列；不触达用户数据目录与 ORM 模型定义。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "employee-pack-curator",
        name: "员工包策展员",
        summary:
            "管理 MODstore 员工包的完整生命周期：AI scaffold、Skill 注册、executor 维护、.xcemp 导入导出与 ESkill 演化固化；不得修改支付模块。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "flask-entry-keeper",
        name: "Flask 入口维护员",
        summary:
            "维护根目录 Flask 应用 app.py 的路由、表单处理、excel-to-ai 动态页与依赖 requirements.txt；对接静态站，不涉及 MODstore 或 Nginx 配置。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "nginx-config-engineer",
        name: "Nginx 配置工程师",
        summary: "维护 xiu-ci.com 所有 Nginx 配置文件，包含虚拟主机、TLS、反代规则；不碰任何业务代码。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "workbench-ux-stylist",
        name: "工作台 UX 设计员",
        summary:
            "专注维护 MODstore 工作台（Workbench）的 UX 与交互：画布、右侧边栏、工作台 Shell、AI 草稿审核组件与整体暗色设计系统；严格遵守 Vue 3 Only。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "java-payment-bridge-officer",
        name: "Java 支付桥接员",
        summary:
            "P-W MODstore Java 支付面：PaymentController、OrderService、PAYMENT_CONTRACT 与 Python 代理对齐。",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
  AiGroupConversation(
    id: "dept:ops_partner",
    name: "O-B 伙伴部",
    memberCount: 6,
    preview: "生态分润对账员：我负责 O-B 生态的伙伴分润对账，联合 GMV 数据核验，以及渠道分润计算与异常校验，确保伙伴收益结算",
    timestampText: "6/24",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "ecosystem-delivery-reporter",
        name: "生态交付回传员",
        summary: "O-B B3 联合包交付遥测 · 里程碑回写 O-A CRM 快照 · 生态进度事件。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "ecosystem-investor-portal-officer",
        name: "投资方只读门户员",
        summary: "O-B B4 投资方/伙伴只读 Portal · 里程碑与风险视图 · 进度只读 API。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "ecosystem-joint-catalog-officer",
        name: "联合 Catalog 策展员",
        summary: "O-B B2 生态联合 SKU · MODstore catalog 扩展 · 伙伴商品挂载与可见性策略。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "ecosystem-partner-onboard-officer",
        name: "生态伙伴接入员",
        summary: "O-B B1 生态伙伴 onboarding · 租户隔离 · 联合 SSO 与伙伴档案建档。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "ecosystem-revenue-share-reconciler",
        name: "生态分润对账员",
        summary:
            "O-B B5 渠道分润 · 联合 GMV 对账 · 与 payment-billing-reconciler 分工（本岗偏伙伴分润）。",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
];
