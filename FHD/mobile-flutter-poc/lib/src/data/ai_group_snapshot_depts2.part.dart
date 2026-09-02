// ignore_for_file: prefer_single_quotes

part of 'ai_group_snapshot.dart';

const _aiGroupSnapshotDepts2 = <AiGroupConversation>[
  AiGroupConversation(
    id: "dept:ops_acquisition",
    name: "O-A 获客部",
    memberCount: 13,
    preview: "需求接入员：收到，部署流程通畅就好。有新的需求或工单我这边随时接收，解析好就推过来。",
    timestampText: "6/22",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "payment-billing-reconciler",
        name: "支付账单对账员",
        summary:
            "维护 MODstore 支付与账单模块：支付宝接口、订单管理、LLM 计费与订阅续费；对账只读为主，禁止直接写生产 DB。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "intake-dispatcher",
        name: "需求接入员",
        summary:
            "把外部输入（admin 自然语言下达、邮件、微信、客服工单、`mianshi/` 候补包、外部 webhook）规整成结构化 task，写入「待派发」队列；本岗只做语义解析与归一化，不直接选员工、不直接改业务代码。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "deploy-release-officer",
        name: "发布部署主管",
        summary:
            "编排 xiu-ci.com 全站的构建与发布流程，包含 Docker 镜像、腾讯云 Pages 部署、脚本维护；不写业务逻辑。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "change-request-auditor",
        name: "变更评审员",
        summary:
            "对员工提交到「待邮件审批」队列的补丁/PR 做自动评审：跑测试 → 静态规则审 → 自动放行低风险 / 升级高风险给 admin；不直接改业务源码、不直接合并到主干。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "modstore-backend-api",
        name: "MODstore 后端 API 员",
        summary:
            "维护 MODstore 平台的 Flask 蓝图 API：工作台、市场目录、工作流、LLM 代理与 WebSocket 实时通道；不触碰前端 Vue 文件。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "seo-sitemap-curator",
        name: "SEO 站点地图管理员",
        summary:
            "维护 xiu-ci.com 的 SEO 资产：sitemap.xml、robots.txt、百度/必应站长校验文件与结构化数据，确保收录与排名质量。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "site-content-editor",
        name: "静态站内容编辑员",
        summary: "维护 xiu-ci.com 营销静态页面的内容、文案、图片引用与数据 JSON；不涉及服务器配置或后端逻辑。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "test-qa-runner",
        name: "测试质量运行员",
        summary:
            "负责全站测试套件的维护与执行：pytest 单元/集成测试、vitest 前端单测、Playwright E2E 测试、pre-commit hooks、覆盖率门禁、CI 工作流测试步骤、TypeScript 类型检查；输出测试结果并推动覆盖率达标；不修改被测源码。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "user-customer-service-officer",
        name: "客户客服",
        summary: "查看并回复企业客户的客服消息",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "delivery-receipt-officer",
        name: "交付签收员",
        summary:
            "O8 里程碑签收与交付确认：对接 OPS_CLOSURE、签收工单、test-qa-runner 门禁与 receipt 工作流。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "enterprise-adoption-officer",
        name: "使用跟踪员",
        summary:
            "跟踪 O6 使用阶段：租户激活、功能采纳、用量遥测与回访触发；与 user-customer-service-officer 分工（本岗偏数据与里程碑，客服偏交互）。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "marketing-site-builder",
        name: "营销站点构建员",
        summary:
            "维护 marketing-site/ Nunjucks 模板与构建脚本（build.mjs、package.json）；与根静态站 site-content-editor 分工：本岗只管独立营销站子项目，不碰 MODstore 与市场 Vue 源码。",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
  AiGroupConversation(
    id: "dept:prod_mod",
    name: "P-M Mod 部",
    memberCount: 18,
    preview: "员工包质询员：我是负责对候选员工包进行结构化面试的，会根据你提交的 manifest、测试日志或沙盒 JSON 来评估是",
    timestampText: "6/22",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "employee-interview-assistant",
        name: "员工信息访谈员",
        summary:
            "面向平台协作场景：通过结构化提问与表单补全，帮助其他员工（及岗位包）补全元数据、能力说明、\n运行依赖与风险字段；不替代 HR 正式录用流程，不存储敏感个人身份信息于未授权位置。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "push-update-context-officer",
        name: "推送更新员工",
        summary: "在合并、推送与发布前汇总当前 Git 状态与设备/部署档位；不直接执行生产发布，不修改业务源码。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "artifact-generator",
        name: "产物生成员工",
        summary: "根据规划蓝图生成员工包产物（manifest、Python 实现、资产文件）；支持 LLM 驱动和资产驱动两种模式",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "code-validator",
        name: "代码校验员工",
        summary: "对员工包体进行轻量校验，包括 manifest 合规性、Python 编译检查、包体一致性、独立可执行验证",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "employee-pack-quality-interviewer",
        name: "员工包质询员",
        summary:
            "对候选 employee_pack（.xcemp）做结构化「入职面试」：基于用户粘贴的 manifest 节选、同步测试日志或\n沙盒 JSON，对照职责边界与平台契约给出录用/有条件录用/驳回结论与可执行修改清单。\n不替代渗透测试、法务合规或正式 HR 录用；不编造未出现在输入中的文件路径、接口或密钥。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "employee-planner",
        name: "规划设计员工",
        summary: "根据结构化需求规划员工包架构，拆分员工职责、脚本工作流与 Skill 组；输出一站式员工蓝图",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "hex-quality-assessor",
        name: "六维质检员工",
        summary: "对制作车间产物执行六维质量评估与放行建议",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "host-checker",
        name: "运维员工",
        summary: "探测宿主环境连通性，验证 LLM 密钥状态、API 版本兼容性与服务可达性",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "intent-analyst",
        name: "需求分析员工",
        summary: "解析用户自然语言需求，提取结构化意图、领域关键词与建议能力；识别用户身份与权限",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "miniapp-builder",
        name: "小程序员工",
        summary: "为员工包生成配套脚本工作流（小程序），将自然语言需求转化为可执行的脚本逻辑",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "mods-and-eskill-curator",
        name: "Mods/ESkill 策展员",
        summary:
            "管理 mods/ 目录中的 Mod 包与 eskill-prototype/ 原型；负责 .xcemp 上架审核流程与 ESkill 标准文档维护；所有上线须经 CI 审批，不直接操作生产 DB。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "pack-registrar",
        name: "打包登记员工",
        summary: "将员工包登记到 Catalog 目录，执行五维审核，生成 .xcemp 发布包",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "quality-validator",
        name: "质检员工",
        summary: "对生成的产物进行服务端校验，包括 manifest 合规性、Python 语法、资产完整性与一致性检查",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "sandbox-tester",
        name: "测试员工",
        summary: "对员工工作流执行沙箱测试，包括结构校验与 Mock 执行验证",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "script-binder",
        name: "配置绑定员工",
        summary: "将生成的脚本工作流嵌入员工包，更新 manifest 能力声明与目录结构",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "self-checker",
        name: "自检员工",
        summary: "执行员工包独立可执行自检，验证 .xcemp 包在隔离环境下可正常加载与运行",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "workflow-automator",
        name: "流程自动化员工",
        summary: "为员工包创建自动化工作流（Skill 组），通过自然语言生成画布节点与连线",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
  AiGroupConversation(
    id: "dept:shared_retention",
    name: "S-R 归档部",
    memberCount: 4,
    preview: "",
    timestampText: "",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "security-secrets-guard",
        name: "安全密钥守卫",
        summary:
            "保护 xiu-ci.com 所有密钥、证书与敏感配置；进行依赖 CVE 扫描、CSP/Headers 审计；发现问题时告警，不自动修改生产配置。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "retention-officer",
        name: "档案清理员",
        summary:
            "周期性清理 workbench_script_runs、上传分片、旋转日志、知识缓存等过期文件，并把每次清理结果写回员工执行流水，作为「定时档案清理」岗位在员工大会上发言。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "legacy-archive-curator",
        name: "工作区归档管理员",
        summary:
            "S-R R3 工作区与 legacy 归档：_archive/、FHD/.archive/、LEGACY_CLEANUP_TRACKING、xcmax-tree 排除项治理。",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
  AiGroupConversation(
    id: "dept:prod_software",
    name: "P-S 软件部",
    memberCount: 8,
    preview: "",
    timestampText: "",
    members: [
      AiGroupMember(
        employeeId: "xcagi-assistant",
        name: "小C助理",
        summary: "AI助手，负责群内上下文、任务拆解和工作汇报串联。",
        avatarUrl: null,
        avatarKey: "assistant",
      ),
      AiGroupMember(
        employeeId: "log-monitor-incident",
        name: "日志监控与事故响应员",
        summary: "归并和分析 xiu-ci.com 所有运行日志、测试报告与覆盖率数据；生成告警摘要并推动事故处置；不修改源码。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "dbops-engineer",
        name: "数据库运维工程师",
        summary:
            "负责 ORM 模型与 Alembic 迁移、慢查询/索引/复制状态诊断、备份恢复策略与权限审计；唯一拥有 models.py / alembic / migrations 写权限的员工，所有 schema 变更必须由本岗发起或评审。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "top-architect",
        name: "顶级架构师员工",
        summary:
            "掌握 XCMAX/FHD/MODstore/移动端/员工体系的全局架构地图，负责架构答疑、学习辅导、升级路线、ADR、跨端影响评审与风险拆解；默认只读分析，变更需派发给对应岗位执行。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "fhd-core-maintainer",
        name: "FHD 核心应用维护员",
        summary:
            "维护 FHD 宿主核心 app/ 与 tests/：应用服务、路由、NeuroBus 集成；产出经 CR Git 管线提交 PR，由 FHD test.yml 与 ci-auto-merge 门控。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "mobile-android-release-officer",
        name: "Android 发版员",
        summary:
            "Flutter Android 渠道构建与发布：统一 Flutter CI、release-android、签名 APK/AAB 与真机 smoke。",
        avatarUrl: null,
        avatarKey: "",
      ),
      AiGroupMember(
        employeeId: "mobile-ios-release-officer",
        name: "iOS 发版员",
        summary:
            "Flutter iOS 渠道发布：Runner、Fastlane match、签名、TestFlight / App Store Connect 上传与 release 门禁。",
        avatarUrl: null,
        avatarKey: "",
      ),
    ],
  ),
];
