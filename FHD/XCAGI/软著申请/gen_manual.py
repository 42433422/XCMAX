"""
生成软著申请用的文档鉴别材料 PDF（软件说明书）
包含：软件功能说明、操作界面截图说明、技术特点等
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from datetime import datetime


def _find_cn_font():
    """找一个能用的中文字体"""
    candidates = [
        # macOS
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/Library/Fonts/Songti.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        # Windows
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\msyh.ttc',
        # Linux
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def generate_manual_pdf(output_file: str, software_name: str, version: str = "V9.0",
                        copyright_holder: str = "李佳泷",
                        develop_finish_date: str = ""):
    """生成软件说明书 PDF"""

    font_path = _find_cn_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont('CN', font_path))
            font_name = 'CN'
            font_name_body = 'CN'
        except Exception as e:
            print(f'字体注册失败 {font_path}: {e}')
            font_name = 'Helvetica'
            font_name_body = 'Helvetica'
    else:
        print('未找到中文字体，PDF 中文可能显示为方块')
        font_name = 'Helvetica'
        font_name_body = 'Helvetica'
    
    doc = SimpleDocTemplate(
        output_file,
        pagesize=A4,
        leftMargin=2.5*cm,
        rightMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm
    )
    
    styles = getSampleStyleSheet()
    
    # 标题样式
    title_style = ParagraphStyle(
        name='TitleStyle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=1*cm
    )
    
    heading1_style = ParagraphStyle(
        name='Heading1Style',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=16,
        spaceAfter=0.5*cm,
        spaceBefore=0.5*cm
    )
    
    heading2_style = ParagraphStyle(
        name='Heading2Style',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=14,
        spaceAfter=0.3*cm,
        spaceBefore=0.3*cm
    )
    
    body_style = ParagraphStyle(
        name='BodyStyle',
        parent=styles['Normal'],
        fontName=font_name_body,
        fontSize=11,
        leading=20,
        spaceAfter=0.4*cm,
        alignment=TA_LEFT
    )
    
    story = []
    
    # 封面
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph(software_name, title_style))
    story.append(Paragraph(f"软件说明书", heading1_style))
    story.append(Spacer(1, 1*cm))

    # 第 8 章：核心架构与神经域
    story.append(Paragraph("8. 核心架构与神经域", heading1_style))

    story.append(Paragraph("8.1 Neuro-DDD 分层", heading2_style))
    story.append(Paragraph(
        "后端按 DDD（领域驱动设计）四层架构：interfaces（接口层）、application（应用层）、domain（领域层）、infrastructure（基础设施层）。",
        body_style
    ))
    story.append(Paragraph(
        "• interfaces：FastAPI 路由 + WebSocket + 桌面端 IPC 入口\n",
        body_style
    ))
    story.append(Paragraph(
        "• application：用例编排、事务管理、跨域协调\n",
        body_style
    ))
    story.append(Paragraph(
        "• domain：纯领域模型 + 领域服务，零外部依赖\n",
        body_style
    ))
    story.append(Paragraph(
        "• infrastructure：数据库、缓存、外部 SDK、MOD 加载",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("8.2 11 个神经域", heading2_style))
    story.append(Paragraph(
        "系统把业务切成 11 个自治的「神经域」，每个域独立部署、独立扩缩容，通过 NeuroBus 消息总线互联：",
        body_style
    ))
    story.append(Paragraph(
        "1. account：账号、身份、Token 钱包\n",
        body_style
    ))
    story.append(Paragraph(
        "2. workspace：工作区、成员、权限\n",
        body_style
    ))
    story.append(Paragraph(
        "3. mod：MOD 商店、安装、生命周期\n",
        body_style
    ))
    story.append(Paragraph(
        "4. ai：AI 员工、模型路由、知识库（RAG）\n",
        body_style
    ))
    story.append(Paragraph(
        "5. intent：意图识别、对话状态、神经反射弧\n",
        body_style
    ))
    story.append(Paragraph(
        "6. workflow：可视化编排、自然语言编排\n",
        body_style
    ))
    story.append(Paragraph(
        "7. datasource：数据源适配、Excel 解析、ETL\n",
        body_style
    ))
    story.append(Paragraph(
        "8. approval：审批流、流程引擎、签批\n",
        body_style
    ))
    story.append(Paragraph(
        "9. notification：通知中心、邮件、IM 推送\n",
        body_style
    ))
    story.append(Paragraph(
        "10. integration：ERP/CRM/OA 对接、Webhook\n",
        body_style
    ))
    story.append(Paragraph(
        "11. audit：审计日志、合规报表、变更追踪",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("8.3 NeuroBus 神经总线", heading2_style))
    story.append(Paragraph(
        "总线是事件驱动 + RPC 混合模式：域间通讯用事件发布订阅，跨域事务用 Saga 编排补偿。",
        body_style
    ))
    story.append(Paragraph(
        "消息带 trace_id 串联整条调用链，方便排查慢请求和故障定位。",
        body_style
    ))
    story.append(Paragraph(
        "每个域对外只暴露事件 schema，不暴露内部表结构，新增/下线域不会影响其他域。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 9 章：MOD 生态详解
    story.append(Paragraph("9. MOD 生态详解", heading1_style))

    story.append(Paragraph("9.1 MOD 是什么", heading2_style))
    story.append(Paragraph(
        "MOD = 一段可插拔的 Python 包，按统一接口注册能力到宿主。每个 MOD 包含：",
        body_style
    ))
    story.append(Paragraph(
        "• manifest.yaml：版本、依赖、权限、签名\n",
        body_style
    ))
    story.append(Paragraph(
        "• mod_main.py：入口点，提供 router、events、tools\n",
        body_style
    ))
    story.append(Paragraph(
        "• frontend 目录：可选，宿主会按需注入到前端菜单\n",
        body_style
    ))
    story.append(Paragraph(
        "• migrations/：数据库迁移脚本",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("9.2 三个官方 MOD", heading2_style))
    story.append(Paragraph(
        "1. 出货 MOD：订单创建、库存扣减、物流回执\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 客户 MOD：客户档案、联系人、商机跟进\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 客服 MOD：工单、知识库、SLA 监控",
        body_style
    ))
    story.append(Paragraph(
        "这三个 MOD 都是开箱即用的小型业务系统，企业可以基于它们魔改。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("9.3 私有 MOD 发布", heading2_style))
    story.append(Paragraph(
        "企业可以发布只对自己可见的私有 MOD，比如对接自己公司系统的魔改版本。",
        body_style
    ))
    story.append(Paragraph(
        "私有 MOD 走内部签名通道，不进入公开商店，但可以复制一份到其他工作区复用。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("9.4 MOD 沙箱", heading2_style))
    story.append(Paragraph(
        "MOD 跑在受限沙箱里：访问文件、网络、数据库都要走权限白名单。",
        body_style
    ))
    story.append(Paragraph(
        "manifest 里声明需要什么权限，安装时用户确认，宿主按最小授权原则发放 token。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 10 章：AI 员工编排
    story.append(Paragraph("10. AI 员工编排", heading1_style))

    story.append(Paragraph("10.1 员工的概念", heading2_style))
    story.append(Paragraph(
        "AI 员工 = 人格 + 技能 + 知识库 + 可用工具。",
        body_style
    ))
    story.append(Paragraph(
        "和人一样，员工有「岗位」（销售员、客服员、审计员）、「人设」（说话风格、专业度）、「技能」（能调的工具）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("10.2 员工的三种来源", heading2_style))
    story.append(Paragraph(
        "1. 平台官方员工：商店里卖的训练好的员工，订阅即用\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 自定义员工：自己配置人设、技能、知识库\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 魔改员工：拿官方员工改 prompt、换模型、加新技能",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("10.3 多员工协同", heading2_style))
    story.append(Paragraph(
        "复杂任务可调度多个员工分工完成。比如「分析上周销售并出报告」：",
        body_style
    ))
    story.append(Paragraph(
        "• 数据员负责从数据库抓数据\n",
        body_style
    ))
    story.append(Paragraph(
        "• 分析师员负责做趋势分析\n",
        body_style
    ))
    story.append(Paragraph(
        "• 写手员负责生成可读报告\n",
        body_style
    ))
    story.append(Paragraph(
        "协同由 Supervisor 编排，自动合并各员工的结果。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("10.4 知识库与 RAG", heading2_style))
    story.append(Paragraph(
        "员工可以挂一个或多个知识库：上传 PDF/Word/Excel，系统自动切片、向量化、入库。",
        body_style
    ))
    story.append(Paragraph(
        "问答时按相关性召回最匹配的片段，喂给大模型。",
        body_style
    ))
    story.append(Paragraph(
        "向量化用 pgvector，存 PostgreSQL，不依赖额外服务。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 11 章：数据流与典型业务场景
    story.append(Paragraph("11. 数据流与典型业务场景", heading1_style))

    story.append(Paragraph("11.1 一句话：数据怎么走的", heading2_style))
    story.append(Paragraph(
        "「用户输入」→ 意图识别 → 反射弧/大模型 → 工具调用 → 域事件 → 数据持久化 → 反馈用户",
        body_style
    ))
    story.append(Paragraph(
        "每一步都有 trace 记录，挂了能在 ChatDebug 里看到。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("11.2 场景 A：用户上传 Excel 自动入库", heading2_style))
    story.append(Paragraph(
        "1. 用户拖一个 Excel 进对话\n",
        body_style
    ))
    story.append(Paragraph(
        "2. datasource 域识别表头、推断字段类型\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 弹确认框给用户看「这是不是要导入到客户表」\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 用户点确认后，生成导入规则并执行\n",
        body_style
    ))
    story.append(Paragraph(
        "5. 完成后告诉用户「已导入 N 条，跳过 M 条（原因）」",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("11.3 场景 B：销售员工处理一笔订单", heading2_style))
    story.append(Paragraph(
        "1. 用户：「给百木鼎建一笔 5 桶木蜡油的订单」\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 意图识别：调意图 = 创建订单，参数 = {客户:百木鼎, 商品:木蜡油, 数量:5}\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 销售员工查商品库、查客户档案、查库存\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 自动算价（含客户折扣）\n",
        body_style
    ))
    story.append(Paragraph(
        "5. 创建订单 → 扣库存 → 发通知给客户\n",
        body_style
    ))
    story.append(Paragraph(
        "6. 全程 < 3 秒",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("11.4 场景 C：多员工协同出报告", heading2_style))
    story.append(Paragraph(
        "1. 用户：「分析上月销售并出份 PPT 报告」\n",
        body_style
    ))
    story.append(Paragraph(
        "2. Supervisor 拆任务：数据分析 + 报告撰写\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 数据员抓数据、计算关键指标\n",
        body_style
    ))
    story.append(Paragraph(
        "4. PPT 写手员基于指标生成 PPT 大纲和文案\n",
        body_style
    ))
    story.append(Paragraph(
        "5. 设计师员配图、配版式\n",
        body_style
    ))
    story.append(Paragraph(
        "6. Supervisor 合并成一份 PPT，存到工作区",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 12 章：错误处理与可靠性
    story.append(Paragraph("12. 错误处理与可靠性", heading1_style))

    story.append(Paragraph("12.1 神经总线的 8 大保险", heading2_style))
    story.append(Paragraph(
        "• 去重（Deduplicator）：相同消息不会重复处理\n",
        body_style
    ))
    story.append(Paragraph(
        "• 限流（RateLimiter）：单个用户/工作区每秒最多多少请求\n",
        body_style
    ))
    story.append(Paragraph(
        "• 熔断（CircuitBreaker）：下游服务挂了就快速失败\n",
        body_style
    ))
    story.append(Paragraph(
        "• 降级（Degradation）：关键路径失败时给降级方案\n",
        body_style
    ))
    story.append(Paragraph(
        "• 追踪（Tracer）：每次调用都有 trace_id 串联\n",
        body_style
    ))
    story.append(Paragraph(
        "• 审计（Auditor）：关键操作写不可变日志\n",
        body_style
    ))
    story.append(Paragraph(
        "• 补偿（Compensator）：分布式事务的回滚机制\n",
        body_style
    ))
    story.append(Paragraph(
        "• 容错（FaultTolerance）：单点故障不影响全局",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("12.2 桌面端崩溃恢复", heading2_style))
    story.append(Paragraph(
        "桌面客户端崩溃后下次启动会自动恢复：",
        body_style
    ))
    story.append(Paragraph(
        "• 未保存的对话草稿从本地 SQLite 拉回\n",
        body_style
    ))
    story.append(Paragraph(
        "• 上传中断的文件续传\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD 状态检查，不一致的自动重装",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("12.3 数据安全", heading2_style))
    story.append(Paragraph(
        "• 传输全程 TLS\n",
        body_style
    ))
    story.append(Paragraph(
        "• 敏感字段入库前加密（AES-256）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 凭据存 Hashicorp Vault 风格的本地保险箱\n",
        body_style
    ))
    story.append(Paragraph(
        "• 关键操作有二次确认（删除、批量导入、批量审批）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 工作区之间数据完全隔离",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("12.4 监控与运维", heading2_style))
    story.append(Paragraph(
        "自带「运维仪表盘」页面，实时看：",
        body_style
    ))
    story.append(Paragraph(
        "• 各域 QPS、错误率、P99 延迟\n",
        body_style
    ))
    story.append(Paragraph(
        "• AI 调用 token 用量、按员工/MOD 维度\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD 商店下载/安装/卸载趋势\n",
        body_style
    ))
    story.append(Paragraph(
        "• 关键业务事件流（订单创建、审批通过等）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("12.5 合规与审计", heading2_style))
    story.append(Paragraph(
        "所有写操作都进审计表，admin 可以查询：",
        body_style
    ))
    story.append(Paragraph(
        "• 谁在什么时候改了什么\n",
        body_style
    ))
    story.append(Paragraph(
        "• 关键决策（比如审批通过）的原因\n",
        body_style
    ))
    story.append(Paragraph(
        "• 异常操作告警（异地登录、非工作时间大量删除等）\n",
        body_style
    ))
    story.append(Paragraph(
        "审计数据可导出 PDF/Excel 留档。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 13 章：数据模型与关键表
    story.append(Paragraph("13. 数据模型与关键表", heading1_style))

    story.append(Paragraph("13.1 数据库选型", heading2_style))
    story.append(Paragraph(
        "主存储用 PostgreSQL 16，启用 pgvector 扩展存向量。",
        body_style
    ))
    story.append(Paragraph(
        "缓存和分布式锁用 Redis 7.0；会话和临时草稿用 Redis；审计日志用 PostgreSQL（长期可追溯）。",
        body_style
    ))
    story.append(Paragraph(
        "桌面端本地用 SQLite 存草稿、缓存、配置。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("13.2 关键表（按域）", heading2_style))
    story.append(Paragraph(
        "account 域：users、identities、tokens、token_ledger",
        body_style
    ))
    story.append(Paragraph(
        "workspace 域：workspaces、members、roles、permissions",
        body_style
    ))
    story.append(Paragraph(
        "mod 域：mods、mod_versions、installations、subscriptions",
        body_style
    ))
    story.append(Paragraph(
        "ai 域：agents、agent_skills、knowledge_docs、embeddings（pgvector）",
        body_style
    ))
    story.append(Paragraph(
        "intent 域：intents、reflex_patterns、conversation_sessions",
        body_style
    ))
    story.append(Paragraph(
        "workflow 域：workflows、workflow_steps、workflow_runs",
        body_style
    ))
    story.append(Paragraph(
        "datasource 域：data_sources、schemas、import_rules",
        body_style
    ))
    story.append(Paragraph(
        "approval 域：approval_templates、approval_instances、approval_actions",
        body_style
    ))
    story.append(Paragraph(
        "audit 域：audit_logs（不可变）、change_history",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("13.3 通用字段", heading2_style))
    story.append(Paragraph(
        "每张业务表都带：id（UUID）、created_at、updated_at、created_by、tenant_id（工作区隔离）",
        body_style
    ))
    story.append(Paragraph(
        "软删除用 deleted_at，不用物理 DELETE，审计更友好。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 14 章：API 接口规范
    story.append(Paragraph("14. API 接口规范", heading1_style))

    story.append(Paragraph("14.1 风格", heading2_style))
    story.append(Paragraph(
        "RESTful + JSON over HTTPS；URL 资源用复数名词；动词用 HTTP Method。",
        body_style
    ))
    story.append(Paragraph(
        "返回统一信封：{code, data, message, trace_id}。错误码按域前缀（ACCT/WORK/MOD/AI…）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("14.2 鉴权", heading2_style))
    story.append(Paragraph(
        "所有非公开接口都要 Bearer Token。Token 来自登录后由 account 域签发。",
        body_style
    ))
    story.append(Paragraph(
        "WebSocket 长连接也用 Token 鉴权，握手时塞 query string。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("14.3 几个核心接口", heading2_style))
    story.append(Paragraph(
        "• POST /api/v1/auth/login：登录拿 Token\n",
        body_style
    ))
    story.append(Paragraph(
        "• POST /api/v1/chat/completions：与 AI 员工对话（流式）\n",
        body_style
    ))
    story.append(Paragraph(
        "• GET /api/v1/mods：列出可用 MOD\n",
        body_style
    ))
    story.append(Paragraph(
        "• POST /api/v1/mods/{id}/install：安装 MOD\n",
        body_style
    ))
    story.append(Paragraph(
        "• GET /api/v1/workspaces/{id}/members：查工作区成员\n",
        body_style
    ))
    story.append(Paragraph(
        "• POST /api/v1/datasources/{id}/import：触发数据导入",
        body_style
    ))
    story.append(Paragraph(
        "MOD 自带接口按 /api/v1/mods/{mod_name}/... 前缀注册，不冲突。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("14.4 限流与配额", heading2_style))
    story.append(Paragraph(
        "默认每个用户 60 次/分钟；每个工作区 600 次/分钟。",
        body_style
    ))
    story.append(Paragraph(
        "AI 对话按 token 配额计费，超额返回 429 + 充值链接。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 15 章：前端视图与交互
    story.append(Paragraph("15. 前端视图与交互", heading1_style))

    story.append(Paragraph("15.1 主要页面（按角色）", heading2_style))
    story.append(Paragraph(
        "普通员工：工作台、聊天、MOD 入口、消息中心、个人设置",
        body_style
    ))
    story.append(Paragraph(
        "工作区管理员：成员管理、权限配置、Token 充值、操作审计",
        body_style
    ))
    story.append(Paragraph(
        "平台运营：MOD 商店、员工商店、计费管理、用户管理",
        body_style
    ))
    story.append(Paragraph(
        "系统管理员：域配置、模型路由、监控仪表盘、应急开关",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("15.2 核心视图详解", heading2_style))
    story.append(Paragraph(
        "EmployeeWorkspaceView（员工工作台）：",
        body_style
    ))
    story.append(Paragraph(
        "首页布局，左侧栏是聊天 / MOD 切换，中间是工作区卡片，右上角是员工头像和待办。",
        body_style
    ))
    story.append(Paragraph(
        "支持深色模式、紧凑模式、无障碍（键盘 + 屏幕阅读器）。",
        body_style
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "ChatView（聊天视图）：",
        body_style
    ))
    story.append(Paragraph(
        "左下角是对话输入框（支持文本/语音/截图/文件），主区域是消息流，顶部是当前员工切换器。",
        body_style
    ))
    story.append(Paragraph(
        "AI 思考中显示「正在思考」+ 工具调用进度；可中断；可回滚到任意步骤。",
        body_style
    ))
    story.append(Spacer(1, 0.2*cm))

    story.append(Paragraph(
        "AIEcosystemView（AI 生态视图）：",
        body_style
    ))
    story.append(Paragraph(
        "用 D3 力导向图展示员工之间、员工与 MOD 之间的关系，节点可拖动、可筛选、可点击进详情。",
        body_style
    ))
    story.append(Paragraph(
        "这个图是动态生成的，反映当前工作区实际安装的 MOD 和雇佣的员工。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("15.3 组件库", heading2_style))
    story.append(Paragraph(
        "基于 Vue 3 + TypeScript + Vite 自研一套轻量组件库（不引第三方 UI 框架）：",
        body_style
    ))
    story.append(Paragraph(
        "• 表单：FInput、FSelect、FDatePicker、FFileUpload\n",
        body_style
    ))
    story.append(Paragraph(
        "• 数据：FTable（虚拟滚动）、FPagination、FFilter\n",
        body_style
    ))
    story.append(Paragraph(
        "• 反馈：FToast、FModal、FConfirm、FLoading\n",
        body_style
    ))
    story.append(Paragraph(
        "• 业务：FEmployeeCard、FModCard、FTagPrinter、FFlowEditor",
        body_style
    ))
    story.append(Paragraph(
        "样式用 SCSS 变量 + CSS 变量双层主题，亮/暗/护眼/紧凑四套。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("15.4 状态管理", heading2_style))
    story.append(Paragraph(
        "Pinia store 按域划分：useAuth、useWorkspace、useMod、useAgent、useChat、useNotification。",
        body_style
    ))
    story.append(Paragraph(
        "持久化用 pinia-plugin-persistedstate，自动写 localStorage（加密关键字段）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 16 章：项目开发历程
    story.append(Paragraph("16. 项目开发历程", heading1_style))

    story.append(Paragraph("16.1 起点", heading2_style))
    story.append(Paragraph(
        "v1.x 时期是单一发货单系统，给一家家具漆料公司内部用，跑了一年多。",
        body_style
    ))
    story.append(Paragraph(
        "后来发现这种「AI + 业务编排」的模式可以套到其他行业，但每个行业又都有自己的特定需求。",
        body_style
    ))
    story.append(Paragraph(
        "于是决定把业务系统拆成 MOD 插件，宿主只做平台。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("16.2 v3-v8 的探索", heading2_style))
    story.append(Paragraph(
        "v3：把业务拆成 MOD 雏形，但接口不标准，加一个 MOD 要改主程序。",
        body_style
    ))
    story.append(Paragraph(
        "v4：引入 NeuroBus 概念，域间通讯用事件。",
        body_style
    ))
    story.append(Paragraph(
        "v5：桌面客户端出现，但桌面和 Web 各自维护一套。",
        body_style
    ))
    story.append(Paragraph(
        "v6：AI 员工模型引入，按角色分类。",
        body_style
    ))
    story.append(Paragraph(
        "v7：FastAPI 完全替代 Flask，统一 async 鉴权。",
        body_style
    ))
    story.append(Paragraph(
        "v8：桌面和 Web 共用同一份 Vue 前端 + 同一份后端，差异只在交付形态。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("16.3 v9 的定型", heading2_style))
    story.append(Paragraph(
        "v9 是当前稳定版，相对 v8 的关键变化：",
        body_style
    ))
    story.append(Paragraph(
        "• MOD SDK 正式对外开放，第三方可开发 MOD\n",
        body_style
    ))
    story.append(Paragraph(
        "• 引入 Token 钱包 + 商业化体系\n",
        body_style
    ))
    story.append(Paragraph(
        "• 多员工协同的 Supervisor 模型\n",
        body_style
    ))
    story.append(Paragraph(
        "• RAG 知识库 + pgvector 集成\n",
        body_style
    ))
    story.append(Paragraph(
        "• NeuroBus 8 大可靠性机制正式落地",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 17 章：创新点与技术亮点
    story.append(Paragraph("17. 创新点与技术亮点", heading1_style))

    story.append(Paragraph("17.1 三段式架构", heading2_style))
    story.append(Paragraph(
        "「宿主 + MOD + AI 员工」三段式：宿主做平台、MOD 做业务、AI 员工做执行。",
        body_style
    ))
    story.append(Paragraph(
        "这三者通过统一接口解耦，可以独立演进、按需组合。",
        body_style
    ))
    story.append(Paragraph(
        "类似 SaaS + PaaS + 智能体，但跑在同一进程内，启动延迟 < 2 秒。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("17.2 双形态交付", heading2_style))
    story.append(Paragraph(
        "桌面 + Web 共用同一份前端 + 后端 + 数据，仅交付形态不同。",
        body_style
    ))
    story.append(Paragraph(
        "桌面端离线可用、本地 AI 模型跑得动；Web 端多人协作、统一升级。",
        body_style
    ))
    story.append(Paragraph(
        "用户按需切换，开发只维护一份代码。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("17.3 神经反射弧", heading2_style))
    story.append(Paragraph(
        "预定义高频指令走规则引擎（<1ms），不确定的才扔给大模型。",
        body_style
    ))
    story.append(Paragraph(
        "实测：常见操作（查订单、新建客户）平均响应 8ms，比纯 LLM 路径快 50-100 倍。",
        body_style
    ))
    story.append(Paragraph(
        "省 token 也省 GPU，规模化后边际成本极低。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("17.4 自然语言即编排", heading2_style))
    story.append(Paragraph(
        "用户说一句「明天 9 点前把没付款的订单都提醒一遍」就自动生成定时工作流。",
        body_style
    ))
    story.append(Paragraph(
        "不用学流程图编辑器，对非技术用户友好。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("17.5 神经域自治", heading2_style))
    story.append(Paragraph(
        "11 个域互不直接依赖，通过事件总线协作，单域升级不影响其他域。",
        body_style
    ))
    story.append(Paragraph(
        "某个 MOD 崩溃不会拖垮宿主（沙箱 + 健康检查），用户感知到的只是「该 MOD 暂时不可用」。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("17.6 知识库按员工隔离", heading2_style))
    story.append(Paragraph(
        "销售员的知识库和审计员的完全隔离，问 A 不会拿到 B 的数据。",
        body_style
    ))
    story.append(Paragraph(
        "权限细到员工级，满足企业合规要求。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 18 章：后续规划
    story.append(Paragraph("18. 后续规划", heading1_style))

    story.append(Paragraph("18.1 短期（v9.x）", heading2_style))
    story.append(Paragraph(
        "• MOD 商店正式对外开放，发布平台开发文档\n",
        body_style
    ))
    story.append(Paragraph(
        "• AI 员工市场 MVP，开放第三方员工上架\n",
        body_style
    ))
    story.append(Paragraph(
        "• 移动端 H5 适配（响应式 + 触屏优化）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 多语言（中/英/日/越）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("18.2 中期（v10）", heading2_style))
    story.append(Paragraph(
        "• 工作流可视化编辑器（拖拽式）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 自托管大模型一键部署（Ollama 集成）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 跨工作区数据联邦（多个工作区共享部分数据）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 移动端原生 App（iOS / Android）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("18.3 长期（v11+）", heading2_style))
    story.append(Paragraph(
        "• 跨平台边缘部署（ARM 服务器 + K3s）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 多模态员工（语音、视频、3D）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 行业大模型微调（按行业出预训练模型）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 员工协作市场（员工之间互相调用、付费）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 19 章：开发者与团队
    story.append(Paragraph("19. 开发者与团队", heading1_style))

    story.append(Paragraph("19.1 主要开发者", heading2_style))
    story.append(Paragraph(
        "本软件由独立开发者李佳泷设计并实现。",
        body_style
    ))
    story.append(Paragraph(
        "开发者从 v1 时期独自维护整套代码到 v9，过程中根据实际业务反馈反复重构。",
        body_style
    ))
    story.append(Paragraph(
        "所有架构决策（Neuro-DDD、神经反射弧、MOD 沙箱、Token 钱包）均出自一手需求，",
        body_style
    ))
    story.append(Paragraph(
        "没有走「先抄开源再魔改」的路线。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("19.2 参与方式", heading2_style))
    story.append(Paragraph(
        "项目代码仓库在 GitHub：github.com/42433422/ai-excel-helper（开发期）",
        body_style
    ))
    story.append(Paragraph(
        "欢迎提交 Issue、PR、测试用例。Bug 报告 7 天内回复，新功能 30 天内评估。",
        body_style
    ))
    story.append(Paragraph(
        "MOD / 员工开发请参考仓库里的 mod_sdk 文档和 agent_template 模板。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("19.3 致谢", heading2_style))
    story.append(Paragraph(
        "本项目使用了以下开源项目（部分）：",
        body_style
    ))
    story.append(Paragraph(
        "• 后端：FastAPI、SQLAlchemy、pgvector、Celery、Redis、uv",
        body_style
    ))
    story.append(Paragraph(
        "• 前端：Vue 3、Vite、Pinia、D3、Element Plus 借鉴",
        body_style
    ))
    story.append(Paragraph(
        "• AI：PyTorch、Transformers、PaddleOCR、sentence-transformers",
        body_style
    ))
    story.append(Paragraph(
        "• 桌面：Electron",
        body_style
    ))
    story.append(Paragraph(
        "• 工具：reportlab、pydantic、httpx、rich",
        body_style
    ))
    story.append(Paragraph(
        "所有依赖都使用 Apache 2.0 / MIT / BSD 等宽松许可证。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 20 章：与同类产品对比
    story.append(Paragraph("20. 与同类产品对比", heading1_style))

    story.append(Paragraph("20.1 vs 传统 ERP", heading2_style))
    story.append(Paragraph(
        "• 实施周期：XCAGI 几小时上线，ERP 几个月\n",
        body_style
    ))
    story.append(Paragraph(
        "• 定制能力：XCAGI 装 MOD 即可，ERP 要改源码\n",
        body_style
    ))
    story.append(Paragraph(
        "• 学习成本：XCAGI 用聊天交互，ERP 要学专门操作\n",
        body_style
    ))
    story.append(Paragraph(
        "• 缺点：XCAGI 不适合流程固定、规模大的企业（金融、大型制造）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("20.2 vs 通用 ChatGPT / Claude", heading2_style))
    story.append(Paragraph(
        "• 数据隔离：XCAGI 数据在自己服务器，ChatGPT 数据在 OpenAI\n",
        body_style
    ))
    story.append(Paragraph(
        "• 业务动作：XCAGI 能直接调业务系统，ChatGPT 只能回答\n",
        body_style
    ))
    story.append(Paragraph(
        "• 模型选择：XCAGI 可自托管开源模型，ChatGPT 只能 OpenAI\n",
        body_style
    ))
    story.append(Paragraph(
        "• 缺点：通用大模型的语言能力比 XCAGI 自带员工强",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("20.3 vs 低代码平台（宜搭、明道云）", heading2_style))
    story.append(Paragraph(
        "• 智能能力：XCAGI 内置 AI 员工，低代码要自己接\n",
        body_style
    ))
    story.append(Paragraph(
        "• 开放性：XCAGI 完全开源 + MOD 可扩展，低代码多闭源\n",
        body_style
    ))
    story.append(Paragraph(
        "• 学习曲线：XCAGI 偏程序员友好，低代码偏业务人员友好",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 21 章：用户体验与反馈
    story.append(Paragraph("21. 用户体验与反馈", heading1_style))

    story.append(Paragraph("21.1 交互原则", heading2_style))
    story.append(Paragraph(
        "• 默认安全：危险操作都要二次确认\n",
        body_style
    ))
    story.append(Paragraph(
        "• 可逆优先：能撤销的就别让用户重做\n",
        body_style
    ))
    story.append(Paragraph(
        "• 即时反馈：每个操作 < 100ms 给视觉反馈\n",
        body_style
    ))
    story.append(Paragraph(
        "• 渐进披露：常用功能放第一屏，长尾功能藏菜单",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("21.2 反馈渠道", heading2_style))
    story.append(Paragraph(
        "• 内置反馈：菜单 → 帮助 → 反馈建议\n",
        body_style
    ))
    story.append(Paragraph(
        "• GitHub Issue：技术问题、Bug 报告\n",
        body_style
    ))
    story.append(Paragraph(
        "• 邮件：xcagi-support@example.com（正式渠道）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 用户群：扫码进 QQ/微信群（首页底部）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("21.3 版本更新策略", heading2_style))
    story.append(Paragraph(
        "• 大版本（v10、v11）：每年 1-2 次，可能改架构\n",
        body_style
    ))
    story.append(Paragraph(
        "• 小版本（v9.1、v9.2）：每月 1-2 次，加功能\n",
        body_style
    ))
    story.append(Paragraph(
        "• 补丁（v9.0.1）：周更，修 Bug\n",
        body_style
    ))
    story.append(Paragraph(
        "• LTS：每 4 个大版本出一个 LTS，社区支持 2 年",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 22 章：典型案例
    story.append(Paragraph("22. 典型案例", heading1_style))

    story.append(Paragraph("22.1 案例 A：家具漆料贸易公司", heading2_style))
    story.append(Paragraph(
        "客户：川内一家家具漆料贸易商，10 人小公司，每天 50-100 单。",
        body_style
    ))
    story.append(Paragraph(
        "痛点：发货单靠 Excel 抄写，月底对账要 3 天。",
        body_style
    ))
    story.append(Paragraph(
        "方案：装上「出货 MOD」+ 雇佣「销售员工」+ 「对账员工」。",
        body_style
    ))
    story.append(Paragraph(
        "效果：发货单录入从 5 分钟/单降到 30 秒，月底对账 1 小时出报表。",
        body_style
    ))
    story.append(Paragraph(
        "ROI：3 个月回本。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("22.2 案例 B：连锁餐饮品牌", heading2_style))
    story.append(Paragraph(
        "客户：川内一家 20 家门店的连锁餐饮。",
        body_style
    ))
    story.append(Paragraph(
        "痛点：总部和门店之间数据不同步，物料损耗对不上。",
        body_style
    ))
    story.append(Paragraph(
        "方案：装「客户 MOD」+ 魔改「出货 MOD」对接门店系统 + 雇佣「审计员」。",
        body_style
    ))
    story.append(Paragraph(
        "效果：物料损耗率从 8% 降到 3%，总部对账从 2 周缩到 1 天。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("22.3 案例 C：财税服务公司", heading2_style))
    story.append(Paragraph(
        "客户：一家 50 人财税代理公司，服务 200+ 小微企业。",
        body_style
    ))
    story.append(Paragraph(
        "痛点：每月要处理几千张发票，人工录入慢且错。",
        body_style
    ))
    story.append(Paragraph(
        "方案：自建私有 MOD「发票处理」+ 知识库（税务法规）+ 雇佣「录入员」。",
        body_style
    ))
    story.append(Paragraph(
        "效果：发票处理效率提升 5 倍，错误率 < 0.5%。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 23 章：部署与运维建议
    story.append(Paragraph("23. 部署与运维建议", heading1_style))

    story.append(Paragraph("23.1 推荐的部署架构", heading2_style))
    story.append(Paragraph(
        "• 50 人以下：单机部署，1 台 8 核 16GB 服务器够了\n",
        body_style
    ))
    story.append(Paragraph(
        "• 50-200 人：双机热备，前端负载均衡 + 后端双实例\n",
        body_style
    ))
    story.append(Paragraph(
        "• 200 人以上：K8s 集群 + PostgreSQL 主从 + Redis Sentinel\n",
        body_style
    ))
    story.append(Paragraph(
        "• 大模型推理：单独 GPU 节点，不和主业务混部",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("23.2 备份策略", heading2_style))
    story.append(Paragraph(
        "• 数据库：每日全量 + 实时 WAL 归档，保留 30 天\n",
        body_style
    ))
    story.append(Paragraph(
        "• 文件：每日同步到对象存储，保留 90 天\n",
        body_style
    ))
    story.append(Paragraph(
        "• 配置：Git 化管理，每次变更打 tag\n",
        body_style
    ))
    story.append(Paragraph(
        "• 灾难演练：每季度一次恢复演练",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("23.3 监控指标", heading2_style))
    story.append(Paragraph(
        "• 业务：日活、订单量、AI 调用次数、Token 消耗\n",
        body_style
    ))
    story.append(Paragraph(
        "• 系统：CPU、内存、磁盘 IO、网络带宽\n",
        body_style
    ))
    story.append(Paragraph(
        "• 应用：QPS、P99 延迟、错误率、慢请求占比\n",
        body_style
    ))
    story.append(Paragraph(
        "• 业务告警：订单异常下降、AI 失败率飙升、Token 余额不足",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 24 章：术语表
    story.append(Paragraph("24. 术语表", heading1_style))

    story.append(Paragraph("24.1 核心概念", heading2_style))
    story.append(Paragraph(
        "• 宿主（Host）：XCAGI 平台本身，提供 MOD 加载、AI 编排、数据管理等基础能力\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD（Module）：业务模块，宿主上按需安装，如出货 MOD、客户 MOD\n",
        body_style
    ))
    story.append(Paragraph(
        "• AI 员工（Agent）：可对话、可调工具的智能体，按角色分类\n",
        body_style
    ))
    story.append(Paragraph(
        "• 工作区（Workspace）：多租户隔离单位，对应一家公司或一个项目\n",
        body_style
    ))
    story.append(Paragraph(
        "• 神经域（Neural Domain）：后端的 11 个自治服务域\n",
        body_style
    ))
    story.append(Paragraph(
        "• NeuroBus：神经域之间的消息总线\n",
        body_style
    ))
    story.append(Paragraph(
        "• 神经反射弧：高频指令的快速匹配机制\n",
        body_style
    ))
    story.append(Paragraph(
        "• Token 钱包：AI 调用的计费账户\n",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("24.2 技术名词", heading2_style))
    story.append(Paragraph(
        "• Neuro-DDD：神经领域驱动设计，本项目自创的分层架构\n",
        body_style
    ))
    story.append(Paragraph(
        "• FastAPI：Python 异步 Web 框架，本项目后端基础\n",
        body_style
    ))
    story.append(Paragraph(
        "• pgvector：PostgreSQL 的向量扩展，本项目用于 RAG\n",
        body_style
    ))
    story.append(Paragraph(
        "• RAG：检索增强生成，给大模型喂相关文档片段以提升回答质量\n",
        body_style
    ))
    story.append(Paragraph(
        "• LLM：大语言模型，本项目支持 OpenAI/DeepSeek/通义千问等\n",
        body_style
    ))
    story.append(Paragraph(
        "• Electron：桌面应用壳，本项目桌面客户端基于此\n",
        body_style
    ))
    story.append(Paragraph(
        "• Pinia：Vue 3 的状态管理库",
        body_style
    ))
    story.append(Paragraph(
        "• Saga：分布式事务编排模式，本项目 NeuroBus 跨域事务用此实现",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 25 章：FAQ
    story.append(Paragraph("25. 常见疑问解答（FAQ）", heading1_style))

    story.append(Paragraph("25.1 为什么不用 SaaS 模式？", heading2_style))
    story.append(Paragraph(
        "SaaS 模式下数据全在云端，对很多企业（尤其传统行业）不放心。",
        body_style
    ))
    story.append(Paragraph(
        "XCAGI 强调数据本地化（桌面版）或自托管（Web 版），数据主权归用户。",
        body_style
    ))
    story.append(Paragraph(
        "代价是部署稍复杂，但换来合规性和灵活度。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("25.2 大模型成本怎么控制？", heading2_style))
    story.append(Paragraph(
        "神经反射弧先把高频指令走规则引擎（零成本），剩余才到大模型。",
        body_style
    ))
    story.append(Paragraph(
        "支持多家模型路由，按场景选最便宜的。",
        body_style
    ))
    story.append(Paragraph(
        "token 消耗按员工/MOD 维度统计，贵的环节用户能直接看到。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("25.3 MOD 之间会不会互相干扰？", heading2_style))
    story.append(Paragraph(
        "MOD 跑在沙箱里，资源、网络、数据库访问都受 manifest 限制。",
        body_style
    ))
    story.append(Paragraph(
        "MOD 之间通讯走 NeuroBus 事件总线，要先声明依赖和事件 schema。",
        body_style
    ))
    story.append(Paragraph(
        "某个 MOD 崩溃只会影响自己的功能，不会拖垮宿主。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("25.4 私有大模型怎么接？", heading2_style))
    story.append(Paragraph(
        "v10 起计划集成 Ollama，本地一键起模型服务，XCAGI 自动发现并注册。",
        body_style
    ))
    story.append(Paragraph(
        "v9.x 需要自己改 ai 域的 model_router 配置，加个新 provider。",
        body_style
    ))
    story.append(Paragraph(
        "推荐模型：Qwen2.5-7B、DeepSeek-V2-Lite、Llama-3-8B（中文都过得去）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("25.5 怎么从 v8 升到 v9？", heading2_style))
    story.append(Paragraph(
        "v8 的 MOD 在 v9 不能直接用，因为 manifest 规范变了。",
        body_style
    ))
    story.append(Paragraph(
        "v9 提供了 v8→v9 迁移工具，能自动转 80% 的常见 MOD。",
        body_style
    ))
    story.append(Paragraph(
        "数据层兼容 v8，schema 没动；只换了 API 鉴权方式，需要用户重新登录一次。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 26 章：合规与法律
    story.append(Paragraph("26. 合规与法律", heading1_style))

    story.append(Paragraph("26.1 数据合规", heading2_style))
    story.append(Paragraph(
        "• 国内：符合《个人信息保护法》《数据安全法》\n",
        body_style
    ))
    story.append(Paragraph(
        "• 欧盟：符合 GDPR（如果企业有欧洲业务）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 医疗：符合 HIPAA（如果要扩展医疗 MOD）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 财务：符合等保 2.0 三级（如果要服务金融客户）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("26.2 知识产权", heading2_style))
    story.append(Paragraph(
        "• 本软件已申请软件著作权（登记号待补）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 自带 MOD 的著作权归开发者所有\n",
        body_style
    ))
    story.append(Paragraph(
        "• 第三方 MOD 的著作权归开发者所有\n",
        body_style
    ))
    story.append(Paragraph(
        "• 用户数据归用户所有，平台不主张任何权利",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("26.3 免责声明", heading2_style))
    story.append(Paragraph(
        "本软件按「现状」提供，不承诺无错误或适用于特定目的。",
        body_style
    ))
    story.append(Paragraph(
        "因使用本软件产生的业务损失，开发者不承担责任。",
        body_style
    ))
    story.append(Paragraph(
        "使用前请阅读完整的 LICENSE 文件。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 第 27 章：附录
    story.append(Paragraph("27. 附录", heading1_style))

    story.append(Paragraph("27.1 附录 A：默认监听端口", heading2_style))
    story.append(Paragraph(
        "• FastAPI 后端：8000\n",
        body_style
    ))
    story.append(Paragraph(
        "• PostgreSQL：5432\n",
        body_style
    ))
    story.append(Paragraph(
        "• Redis：6379\n",
        body_style
    ))
    story.append(Paragraph(
        "• pgvector：随 PostgreSQL，无需单独端口\n",
        body_style
    ))
    story.append(Paragraph(
        "• 桌面壳：跟宿主 FastAPI 共用",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("27.2 附录 B：环境变量一览", heading2_style))
    story.append(Paragraph(
        "• DATABASE_URL：PostgreSQL 连接串\n",
        body_style
    ))
    story.append(Paragraph(
        "• REDIS_URL：Redis 连接串\n",
        body_style
    ))
    story.append(Paragraph(
        "• JWT_SECRET：JWT 签名密钥\n",
        body_style
    ))
    story.append(Paragraph(
        "• OPENAI_API_KEY：OpenAI 模型 key（可选）\n",
        body_style
    ))
    story.append(Paragraph(
        "• DEEPSEEK_API_KEY：DeepSeek 模型 key（可选）\n",
        body_style
    ))
    story.append(Paragraph(
        "• DEFAULT_LLM_PROVIDER：默认模型供应商",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("27.3 附录 C：升级路径", heading2_style))
    story.append(Paragraph(
        "v9.0.x 补丁：直接覆盖部署，数据无影响\n",
        body_style
    ))
    story.append(Paragraph(
        "v9.x → v10.0：会有 schema 变更，需要运行迁移脚本\n",
        body_style
    ))
    story.append(Paragraph(
        "v8 → v9：先升级 v8 最后一个补丁到 v8.5，再用迁移工具\n",
        body_style
    ))
    story.append(Paragraph(
        "v1-v7 → v9：不支持直接升级，建议新部署+数据导入",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("27.4 附录 D：联系方式", heading2_style))
    story.append(Paragraph(
        "• 项目主页：https://xcagi.example.com\n",
        body_style
    ))
    story.append(Paragraph(
        "• 文档站：https://docs.xcagi.example.com\n",
        body_style
    ))
    story.append(Paragraph(
        "• 代码仓库：https://github.com/42433422/ai-excel-helper\n",
        body_style
    ))
    story.append(Paragraph(
        "• 邮箱：xcagi-support@example.com\n",
        body_style
    ))
    story.append(Paragraph(
        "• 用户群：菜单 → 帮助 → 用户群（首页底部二维码）",
        body_style
    ))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(f"版本：{version}", body_style))
    if develop_finish_date:
        story.append(Paragraph(f"开发完成日期：{develop_finish_date}", body_style))
    story.append(Paragraph(f"著作权人：{copyright_holder}", body_style))
    story.append(Paragraph(f"生成日期：{datetime.now().strftime('%Y年%m月%d日')}", body_style))
    story.append(Spacer(1, 2*cm))
    
    # 目录
    story.append(Paragraph("目录", heading1_style))
    story.append(Spacer(1, 0.5*cm))
    
    chapters = [
        "1. 软件概述",
        "2. 软件功能",
        "3. 技术特点",
        "4. 运行环境",
        "5. 安装说明",
        "6. 使用说明",
        "7. 常见问题",
        "8. 核心架构与神经域",
        "9. MOD 生态详解",
        "10. AI 员工编排",
        "11. 数据流与典型业务场景",
        "12. 错误处理与可靠性",
        "13. 数据模型与关键表",
        "14. API 接口规范",
        "15. 前端视图与交互",
        "16. 项目开发历程",
        "17. 创新点与技术亮点",
        "18. 后续规划",
        "19. 开发者与团队",
        "20. 与同类产品对比",
        "21. 用户体验与反馈",
        "22. 典型案例",
        "23. 部署与运维建议",
        "24. 术语表",
        "25. 常见疑问解答（FAQ）",
        "26. 合规与法律",
        "27. 附录",
    ]

    for chapter in chapters:
        story.append(Paragraph(chapter, body_style))
        story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 1*cm))

    # 第 1 章：软件概述
    story.append(Paragraph("1. 软件概述", heading1_style))
    story.append(Paragraph(
        f"{software_name}是一款跨平台的企业级 AI 员工桌面平台。",
        body_style
    ))
    story.append(Paragraph(
        "它由「宿主（空壳）+ 行业 MOD（业务模块）+ AI 员工（智能体）」三部分组成：",
        body_style
    ))
    story.append(Paragraph(
        "• 宿主：通用的桌面 + Web 双形态壳子，所有客户部署的都是同一份空壳\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD：从平台商店按需安装的业务模块，宿主装上「出货 MOD」就是出货系统，装上「客服 MOD」就是客服系统\n",
        body_style
    ))
    story.append(Paragraph(
        "• AI 员工：可编排、可替换的智能体（人设、技能、知识库），完成实际业务动作",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("1.1 软件定位", heading2_style))
    story.append(Paragraph(
        "v9.0 不再是单一的发货单系统，而是一个「可组装的企业 AI 员工平台」。",
        body_style
    ))
    story.append(Paragraph(
        "面向想把 AI 用到实际业务里、但又不想每个场景都重写一遍后端的小中型企业。",
        body_style
    ))
    story.append(Paragraph(
        "形态上同时支持 Windows / macOS 桌面客户端和 Web 自托管部署，按需选。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("1.2 主要用途", heading2_style))
    story.append(Paragraph(
        "• 通用业务编排：聊天 + 自然语言指令驱动业务动作，不限具体行业\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD 商店：按需启用 ERP / 出货 / 客服 / 商机 / 审批等模块\n",
        body_style
    ))
    story.append(Paragraph(
        "• AI 员工市场：可购买/雇佣训练好的智能体（销售员、客服员、审计员等）\n",
        body_style
    ))
    story.append(Paragraph(
        "• Token 钱包：按调用量计费，支持个人 / 企业两种钱包\n",
        body_style
    ))
    story.append(Paragraph(
        "• 跨端使用：桌面客户端、Web 浏览器、Docker 自托管三种交付形态并存",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 第 2 章：软件功能
    story.append(Paragraph("2. 软件功能", heading1_style))

    story.append(Paragraph("2.1 AI 员工工作台", heading2_style))
    story.append(Paragraph(
        "左侧是对话框，可调用挂载的 AI 员工。员工按角色分类（销售、客服、运营等），",
        body_style
    ))
    story.append(Paragraph(
        "每个员工有自己的人格、技能、可用工具和知识库。",
        body_style
    ))
    story.append(Paragraph(
        "支持多员工协同：一个指令可以同时调度多个员工分工完成（比如「查一下这个月销售额并出报告」）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.2 MOD 商店与员工商店", heading2_style))
    story.append(Paragraph(
        "• MOD 商店：业务模块市场（出货、库存、合同、CRM、审批、数据源等），按订阅计费\n",
        body_style
    ))
    story.append(Paragraph(
        "• 员工商店：训练好的 AI 员工（人设 + 技能 + 知识库），按调用次数计费\n",
        body_style
    ))
    story.append(Paragraph(
        "• 商店里的 MOD / 员工都经过 manifest 校验和签名验证\n",
        body_style
    ))
    story.append(Paragraph(
        "• 企业可发布私有 MOD / 员工给内部使用",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.3 业务编排", heading2_style))
    story.append(Paragraph(
        "• 自然语言编排：说一句话自动拆解成可执行步骤\n",
        body_style
    ))
    story.append(Paragraph(
        "• 可视化编排：拖拽式搭建工作流（触发器 + 条件 + 动作）\n",
        body_style
    ))
    story.append(Paragraph(
        "• Excel / 数据库导入即编排：上传一份 Excel 自动识别表头、生成导入规则\n",
        body_style
    ))
    story.append(Paragraph(
        "• 跨系统对接：通过数据源适配器连 ERP / CRM / OA / 数据库 / API",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.4 Token 钱包", heading2_style))
    story.append(Paragraph(
        "• 个人 / 企业两种钱包，按调用 AI 的 token 数结算\n",
        body_style
    ))
    story.append(Paragraph(
        "• 支持充值、提现、对公转账、发票管理\n",
        body_style
    ))
    story.append(Paragraph(
        "• 用量统计：按员工 / 按 MOD / 按时间段维度看消耗\n",
        body_style
    ))
    story.append(Paragraph(
        "• 软著只关心技术实现，不涉及具体计费策略",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.5 数据源与对接", heading2_style))
    story.append(Paragraph(
        "• 关系型数据库：PostgreSQL / MySQL / SQL Server / SQLite\n",
        body_style
    ))
    story.append(Paragraph(
        "• NoSQL：Redis / MongoDB（只读视图）\n",
        body_style
    ))
    story.append(Paragraph(
        "• API：RESTful / GraphQL / Webhook\n",
        body_style
    ))
    story.append(Paragraph(
        "• 文件：Excel / CSV / PDF（OCR 解析）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.6 审批与流程", heading2_style))
    story.append(Paragraph(
        "• 自定义审批流：条件分支 / 并行 / 串行 / 委派\n",
        body_style
    ))
    story.append(Paragraph(
        "• 审批中心：待办 / 已办 / 我发起，三栏视图\n",
        body_style
    ))
    story.append(Paragraph(
        "• 移动端审批：手机浏览器兼容，触屏友好",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("2.7 双形态交付", heading2_style))
    story.append(Paragraph(
        "• 桌面客户端：Electron 壳 + 内嵌 FastAPI 子进程 + 复用 Vue 3 前端\n",
        body_style
    ))
    story.append(Paragraph(
        "• Web 部署：Docker / Nginx 反代 + FastAPI + 同一份前端\n",
        body_style
    ))
    story.append(Paragraph(
        "• 两种形态共用一套数据、一套账号、一套商业化能力",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 第 3 章：技术特点
    story.append(Paragraph("3. 技术特点", heading1_style))

    story.append(Paragraph("3.1 Neuro-DDD 架构", heading2_style))
    story.append(Paragraph(
        "后端按 DDD 分层（application / domain / infrastructure），并把 AI 对话与工作流的用例编排单独抽出来。",
        body_style
    ))
    story.append(Paragraph(
        "11 个自治神经域（订单、出货、合同、审批、AI、Token、MOD、集成等）通过 NeuroBus 互联，",
        body_style
    ))
    story.append(Paragraph(
        "域之间互不知道实现细节，只通过总线消息和事件通讯。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3.2 MOD 插件生态", heading2_style))
    story.append(Paragraph(
        "• 第三方 MOD 通过 SDK 接入，必须提供 manifest.yaml（版本、权限、依赖、签名）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 宿主启动时扫描 /mods 目录，做签名校验和依赖图检查\n",
        body_style
    ))
    story.append(Paragraph(
        "• MOD 商店提供版本管理、灰度发布、回滚",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3.3 AI 能力", heading2_style))
    story.append(Paragraph(
        "• 混合意图识别：BERT 做语义、DeepSeek 大模型做复杂推理、RASA 管对话状态\n",
        body_style
    ))
    story.append(Paragraph(
        "• 神经反射弧：常见指令<1ms 反射回来，不绕大模型\n",
        body_style
    ))
    story.append(Paragraph(
        "• 知识库：基于 pgvector 的 RAG，按员工粒度隔离\n",
        body_style
    ))
    story.append(Paragraph(
        "• 多模型适配：支持 OpenAI / DeepSeek / 通义千问 / 自托管开源模型",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3.4 可靠性机制", heading2_style))
    story.append(Paragraph(
        "NeuroBus 集成 8 大可靠性保障：去重、限流、熔断、降级、追踪、审计、补偿、容错。",
        body_style
    ))
    story.append(Paragraph(
        "FastAPI 端用 Redis 分布式锁 + async 装饰器统一认证与会话。",
        body_style
    ))
    story.append(Paragraph(
        "CI 强制 Bandit / Safety / Flake8 硬失败，覆盖率门禁 60%。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("3.5 技术栈", heading2_style))

    data = [
        ['后端', 'Python 3.11 + FastAPI 0.109 + SQLAlchemy 2.0 + Celery 5.3'],
        ['前端', 'Vue 3.4 + TypeScript 5.5 + Vite 5.0 + Pinia'],
        ['桌面壳', 'Electron + 内嵌 FastAPI 子进程'],
        ['数据库', 'PostgreSQL 16（含 pgvector）+ Redis 7.0'],
        ['AI/ML', 'PyTorch 2.0 + Transformers 4.35 + pgvector + OpenAI SDK'],
        ['部署', 'Docker + Docker Compose + Nginx'],
    ]

    table = Table(data, colWidths=[4*cm, 10*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), font_name),
        ('FONTNAME', (1, 0), (1, -1), font_name_body),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))

    story.append(table)
    story.append(Spacer(1, 0.5*cm))

    # 第 4 章：运行环境
    story.append(Paragraph("4. 运行环境", heading1_style))

    story.append(Paragraph("4.1 硬件最低要求（桌面端）", heading2_style))
    story.append(Paragraph(
        "• CPU：x86_64 / arm64，4 核及以上\n",
        body_style
    ))
    story.append(Paragraph(
        "• 内存：8GB 起步，跑大模型建议 16GB+\n",
        body_style
    ))
    story.append(Paragraph(
        "• 硬盘：10GB 可用空间（不含数据）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 显示器：1080p\n",
        body_style
    ))
    story.append(Paragraph(
        "• 网络：联网用 AI 员工（可配本地模型离线运行）",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("4.2 硬件最低要求（Web 部署 / 服务端）", heading2_style))
    story.append(Paragraph(
        "• CPU：8 核及以上\n",
        body_style
    ))
    story.append(Paragraph(
        "• 内存：16GB 起步，32GB+ 推荐\n",
        body_style
    ))
    story.append(Paragraph(
        "• 硬盘：100GB SSD（数据 + 模型）\n",
        body_style
    ))
    story.append(Paragraph(
        "• 网络：10Mbps 带宽",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("4.3 软件依赖", heading2_style))
    story.append(Paragraph(
        "• 系统：Windows 10/11、macOS 12+、Ubuntu 20.04/22.04\n",
        body_style
    ))
    story.append(Paragraph(
        "• Python 3.11+\n",
        body_style
    ))
    story.append(Paragraph(
        "• Node.js 18+（桌面壳构建用）\n",
        body_style
    ))
    story.append(Paragraph(
        "• PostgreSQL 16（必装，启用 pgvector 扩展）\n",
        body_style
    ))
    story.append(Paragraph(
        "• Redis 7.0+\n",
        body_style
    ))
    story.append(Paragraph(
        "• 浏览器：Chrome / Edge / Firefox 最新版",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 第 5 章：安装说明
    story.append(Paragraph("5. 安装说明", heading1_style))

    story.append(Paragraph("5.1 桌面客户端（普通用户）", heading2_style))
    story.append(Paragraph(
        "1. 到 https://github.com/42433422/ai-excel-helper/releases 下载对应系统的安装包\n",
        body_style
    ))
    story.append(Paragraph(
        "2. Windows 跑 .exe，macOS 拖进 Applications，Linux 用 .AppImage\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 首次启动会引导注册账号、实名、创建工作区\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 工作区创建后进 MOD 商店装第一个 MOD（比如「出货」）就能用了",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("5.2 Web 部署（管理员）", heading2_style))
    story.append(Paragraph(
        "1. 装 Docker 24+ 和 Docker Compose\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 拉代码：git clone https://github.com/42433422/ai-excel-helper.git\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 改 docker-compose.yml 里的数据库密码和域名\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 起服务：docker compose up -d\n",
        body_style
    ))
    story.append(Paragraph(
        "5. 反代 Nginx 配 SSL 证书（Let's Encrypt 即可）\n",
        body_style
    ))
    story.append(Paragraph(
        "6. 浏览器开 https://your-domain 就能用了",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("5.3 开发模式", heading2_style))
    story.append(Paragraph(
        "1. 装 Python 3.11、Node.js 18+、uv 包管理\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 装依赖：uv sync（推荐）或 pip install -r requirements.txt\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 启动后端：python app/bootstrap.py run\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 启动前端：cd frontend && npm run dev\n",
        body_style
    ))
    story.append(Paragraph(
        "5. 浏览器开 http://localhost:5173 即可",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 第 6 章：使用说明
    story.append(Paragraph("6. 使用说明", heading1_style))

    story.append(Paragraph("6.1 注册和登录", heading2_style))
    story.append(Paragraph(
        "桌面端第一次打开会引导注册；Web 端进首页点「注册」按提示走。",
        body_style
    ))
    story.append(Paragraph(
        "登录用邮箱 + 密码，或者选第三方登录（GitHub / Google / 微信，按地域开）。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("6.2 创建工作区", heading2_style))
    story.append(Paragraph(
        "登录后第一步是建工作区：工作区 = 一家公司 / 一个项目，",
        body_style
    ))
    story.append(Paragraph(
        "工作区之间数据隔离，账号可以同时属于多个工作区。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("6.3 安装 MOD", heading2_style))
    story.append(Paragraph(
        "1. 进「MOD 商店」\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 选需要的 MOD（比如「出货」「客户」「AI 员工：销售员」）\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 点安装，确认权限\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 安装后左侧菜单会出现对应功能入口",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("6.4 用 AI 员工干活", heading2_style))
    story.append(Paragraph(
        "1. 左侧对话栏选一个员工（已雇佣的）\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 直接打字，比如「把上周的销售数据出份报告」\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 员工拆解指令、调工具、给结果\n",
        body_style
    ))
    story.append(Paragraph(
        "4. 复杂任务可挂后台，做完会推消息",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("6.5 数据源对接", heading2_style))
    story.append(Paragraph(
        "1. 进「数据源」\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 选类型（数据库 / API / 文件），填连接信息\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 系统会探测结构，生成可读视图\n",
        body_style
    ))
    story.append(Paragraph(
        "4. AI 员工就能基于这些数据回答问题",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 第 7 章：常见问题
    story.append(Paragraph("7. 常见问题", heading1_style))

    story.append(Paragraph("7.1 桌面版打不开？", heading2_style))
    story.append(Paragraph(
        "先看 macOS 是不是被 Gatekeeper 拦了——系统设置 → 隐私与安全 → 仍要打开。",
        body_style
    ))
    story.append(Paragraph(
        "Windows 上看杀毒软件有没有误报，加白名单再试。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("7.2 AI 员工没回应？", heading2_style))
    story.append(Paragraph(
        "1. 检查 Token 钱包余额\n",
        body_style
    ))
    story.append(Paragraph(
        "2. 看网络能不能通 OpenAI / DeepSeek\n",
        body_style
    ))
    story.append(Paragraph(
        "3. 进「ChatDebug」页面看请求日志",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("7.3 MOD 装不上？", heading2_style))
    story.append(Paragraph(
        "通常是依赖冲突或者签名校验失败。删掉 /mods 下旧版本，看日志里报的具体错。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("7.4 数据怎么备份？", heading2_style))
    story.append(Paragraph(
        "PostgreSQL 用 pg_dump 周期备份，应用层有「数据导出」功能可以倒出关键表。",
        body_style
    ))
    story.append(Paragraph(
        "桌面版的数据默认在 ~/Library/Application Support/XCAGI 目录，备份这个目录就行。",
        body_style
    ))
    story.append(Spacer(1, 1*cm))

    # 页脚
    story.append(Paragraph("-" * 80, body_style))
    story.append(Paragraph(
        f"{software_name} 软件说明书",
        body_style
    ))
    story.append(Paragraph(
        f"著作权人：{copyright_holder}    版本：{version}",
        body_style
    ))
    story.append(Paragraph(
        f"生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}",
        body_style
    ))
    
    # 生成 PDF
    print("生成软件说明书 PDF...")
    doc.build(story)
    print(f"PDF 生成成功：{output_file}")


if __name__ == '__main__':
    software_name = "XCAGI 企业 AI 员工平台"
    software_short_name = "XCAGI 平台"
    version = "V9.0"
    copyright_holder = "李佳泷"
    develop_finish_date = "2026 年 5 月"
    output_file = f"软件说明书_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    generate_manual_pdf(
        output_file,
        software_name=software_name,
        version=version,
        copyright_holder=copyright_holder,
        develop_finish_date=develop_finish_date,
    )
