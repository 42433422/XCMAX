#!/usr/bin/env python3
"""知识库检索质量评测：recall@k / MRR，自带 69 条中文查询（含 15 篇干扰文档），可重复运行。

用法（在 FHD/ 下）::

    .venv/bin/python scripts/dev/knowledge_retrieval_eval.py
    FHD_EMBEDDING_MODE=local .venv/bin/python scripts/dev/knowledge_retrieval_eval.py
    FHD_RERANK_ENABLED=1 .venv/bin/python scripts/dev/knowledge_retrieval_eval.py --rerank

默认使用当前进程的 embedding 配置；未配置时是 hash 降级，指标只代表降级基线。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

DOCS: list[dict[str, str]] = [
    {
        "id": "refund-policy",
        "text": "退款政策：客户在签收后七天内可申请无理由退款，超过七天需提供质量问题证明。"
        "退款审批由财务负责人确认，原路退回，三到五个工作日到账。",
    },
    {
        "id": "install-guide",
        "text": "桌面安装指南：Windows 下载安装包后双击运行，macOS 拖入应用程序目录。"
        "安装完成后首次登录需要输入企业账号，安装回执会自动上报到管理端。",
    },
    {
        "id": "invoice-rules",
        "text": "开票规则：增值税专用发票需要客户提供税号、开户行和地址。"
        "普通发票可在订单详情页自助申请，电子发票一个工作日内发送到预留邮箱。",
    },
    {
        "id": "attendance",
        "text": "考勤制度：上班时间九点到十八点，迟到超过三十分钟按半天事假处理。"
        "外勤打卡需要在企业微信提交定位，补卡每月最多三次。",
    },
    {
        "id": "delivery",
        "text": "交付流程：企业客户下单后由交付中心分配安装任务，"
        "客户完成首次登录视为交付完成，未安装的订单进入待安装队列。",
    },
    {
        "id": "permissions",
        "text": "权限说明：管理员可以分配模块和员工包，普通成员只能访问被授权的业务页面。"
        "越权访问会被审计日志记录并拒绝。",
    },
    {
        "id": "backup",
        "text": "数据备份：系统每天凌晨三点自动备份数据库，保留最近十四天。"
        "恢复演练每季度一次，备份文件加密存储。",
    },
    {
        "id": "model-config",
        "text": "模型配置：平台模型需要在管理端填写供应商、接口地址和密钥，"
        "保存后立即生效；BYOK 密钥加密存储，不在前端展示明文。",
    },
    {
        "id": "approval",
        "text": "审批规则：涉及金额超过五万元的采购需要两级审批，"
        "审批人依次为部门负责人和财务负责人，超时三天自动提醒。",
    },
    {
        "id": "export",
        "text": "数据导出：订单和客户列表支持导出 Excel，导出任务异步执行，"
        "完成后在消息中心下载，文件保留七天。",
    },
    {
        "id": "security",
        "text": "账号安全：连续五次密码错误会锁定三十分钟，管理员可以重置密码并强制下线。"
        "异地登录需要二次验证，登录记录可在安全日志查看。",
    },
    {
        "id": "shipping",
        "text": "发货规则：现货订单当天下午四点前付款当天发出，预售订单按承诺日期发出。"
        "物流单号会在发货后自动同步到订单详情页。",
    },
    {
        "id": "inventory",
        "text": "库存管理：低于安全库存时自动生成补货提醒，盘点差异需要仓库主管确认后调整。"
        "库存流水保留一年，支持按商品查询。",
    },
    {
        "id": "contract",
        "text": "合同签署：电子合同通过短信验证码确认身份，签署完成后自动归档到客户档案。"
        "合同变更需要双方重新签署，旧版本保留可追溯。",
    },
    {
        "id": "onboarding",
        "text": "新员工入职：入职当天开通账号并分配部门，试用期三个月。"
        "转正申请需要直属主管和人事审批，通过后同步更新权限。",
    },
    {
        "id": "customer-tier",
        "text": "客户分级：年采购额超过一百万为战略客户，享受专属客户经理和优先交付。"
        "普通客户按季度评估，等级变化会同步到报价策略。",
    },
    {
        "id": "refund-freight",
        "text": "退货运费：质量问题由商家承担来回运费，七天无理由退货由客户承担寄回运费。"
        "运费险理赔需要在退货完成后发起。",
    },
    {
        "id": "data-retention",
        "text": "数据保留：业务数据默认保留三年，日志保留一百八十天。"
        "客户注销后三十天内删除个人数据，备份中的副本按备份周期自然过期。",
    },
    {
        "id": "api-limit",
        "text": "接口限流：单个账号每分钟最多三百次请求，超限返回 429 并提示重试时间。"
        "批量导入走异步任务，不受实时接口限流影响。",
    },
    {
        "id": "print-template",
        "text": "打印模板：标签模板支持变量占位和条码，模板修改后需要重新发布才生效。"
        "打印任务失败会在队列里保留并允许重试。",
    },
    {
        "id": "expense-reimburse",
        "text": "差旅报销：出差住宿按城市等级限额，一线城市每晚不超过六百元。"
        "报销单需要附发票和行程单，财务审核后三个工作日打款到工资卡。",
    },
    {
        "id": "leave-policy",
        "text": "请假制度：年假按工龄计算，未休完的年假可以顺延到次年第一季度。"
        "病假超过两天需要提供医院证明，事假按天扣减当月工资。",
    },
    {
        "id": "training",
        "text": "培训管理：新员工入职培训每月一期，产品培训每季度更新课件。"
        "培训完成情况计入转正评估，外部课程需要主管审批后报名。",
    },
    {
        "id": "procurement",
        "text": "采购流程：单笔超过一万元需要三家供应商比价，比价结果随申请单一并提交。"
        "采购到货后由仓管验收，验收差异在三个工作日内反馈。",
    },
    {
        "id": "supplier",
        "text": "供应商管理：准入需要营业执照、开户许可证和质量管理体系证书。"
        "年度评审按交付及时率和质量合格率打分，不合格供应商进入观察名单。",
    },
    {
        "id": "quality",
        "text": "质量检验：来料按批次抽检，抽检不合格整批退回并记录供应商。"
        "成品出厂前做全检，连续两批不合格暂停合作并要求整改报告。",
    },
    {
        "id": "logistics",
        "text": "物流跟踪：承运商每两小时回传一次轨迹，异常停留超过十二小时自动预警。"
        "签收异常由客服跟进，丢件按保价金额赔付。",
    },
    {
        "id": "warranty",
        "text": "保修条款：整机保修一年，主要部件保修三年，人为损坏不在保修范围。"
        "保修需要提供购买凭证，返修周期一般为七到十个工作日。",
    },
    {
        "id": "subscription",
        "text": "订阅续费：订阅到期前七天发送提醒，默认自动续费一年。"
        "关闭自动续费后仍可使用到当期结束，历史订单可在账单页下载。",
    },
    {
        "id": "privacy",
        "text": "隐私政策：收集的手机号和地址仅用于交付和售后，不会出售给第三方。"
        "需要共享给承运商时只提供必要字段，用户可申请导出或删除个人数据。",
    },
    {
        "id": "release",
        "text": "版本发布：发布前需要通过单元测试、安全扫描和灰度验证。"
        "灰度覆盖百分之十客户且观察四十八小时，回滚窗口为发布后一周。",
    },
    {
        "id": "mobile",
        "text": "手机端支持：iOS 需要十五以上版本，Android 需要十以上版本。"
        "平板按手机布局展示，消息推送依赖系统通知权限。",
    },
    {
        "id": "sso",
        "text": "单点登录：支持企业微信、钉钉和标准 OIDC 三种方式接入。"
        "首次绑定需要管理员在后台开启，解绑后只能用账号密码登录。",
    },
    {
        "id": "notification",
        "text": "通知设置：订单、审批和交付事件默认推送站内消息，可按模块关闭。"
        "重要安全提醒不可关闭，邮件通知需要先验证邮箱。",
    },
    {
        "id": "storage",
        "text": "存储空间：每个企业默认一百 GB 附件空间，超出后按年扩容。"
        "单文件上限两百 MB，回收站文件保留三十天后彻底删除。",
    },
    {
        "id": "audit",
        "text": "审计追踪：配置修改、权限变更和登录行为都会写入审计日志。"
        "管理员可按操作人和时间检索，日志不可编辑，导出需要二次确认。",
    },
    {
        "id": "pricing",
        "text": "报价规则：标准产品按价格表报价，折扣超过九折需要销售主管审批。"
        "定制报价先由售前评估工作量，报价单有效期三十天。",
    },
    {
        "id": "customization",
        "text": "定制开发：客户提出的个性化功能先做需求评估，确认后进入排期。"
        "定制内容以版本化 Mod 交付，升级宿主时保留客户数据与授权。",
    },
    {
        "id": "sla",
        "text": "服务等级：核心接口可用性承诺百分之九十九点九，故障响应不超过三十分钟。"
        "月度可用性未达标按比例返还服务费，重大故障提供复盘报告。",
    },
    {
        "id": "offboarding",
        "text": "离职流程：员工提交离职申请后由主管和人事审批，最后工作日当天回收账号。"
        "账号回收后立即失去所有业务权限，工作交接清单需双方签字确认。",
    },
    {
        "id": "refund-policy-vip",
        "text": "VIP 客户退款：VIP 客户签收后十五天内可申请无理由退款，享有专属客服通道。"
        "VIP 退款审批由客户成功经理确认，退款金额原路退回，两个工作日内到账。",
    },
    {
        "id": "approval-small",
        "text": "小额采购审批：单笔五千元以下的采购由部门组长审批，无需财务复核。"
        "五千元到五万元由部门负责人审批，审批通过后直接生成采购单。",
    },
    {
        "id": "permissions-guest",
        "text": "访客权限：访客账号只能查看被授权的只读页面，不能编辑、导出或下载附件。"
        "访客邀请有效期七天，到期自动失效，续期需要管理员重新授权。",
    },
    {
        "id": "backup-offsite",
        "text": "异地备份：核心数据库每周日做一次异地全量备份，备份文件加密后上传对象存储。"
        "异地恢复演练每半年一次，恢复目标时间不超过四小时。",
    },
    {
        "id": "shipping-holiday",
        "text": "节假日发货：法定节假日不安排发货，节前最后一个工作日下午两点前付款的订单当天发出。"
        "节假日期间的订单在节后第一个工作日按付款顺序顺延发出。",
    },
    {
        "id": "invoice-red",
        "text": "发票红冲：发票开错需要先申请红冲，红冲确认后重新开具正确发票。"
        "跨月红冲需要客户提供情况说明，红冲记录保留在订单开票历史中。",
    },
    {
        "id": "attendance-remote",
        "text": "外勤打卡：外勤人员在客户现场打卡需要开启定位并上传现场照片。"
        "定位偏差超过五百米需要主管确认，外勤记录同步到考勤月报。",
    },
    {
        "id": "security-2fa",
        "text": "二次验证：异地登录、修改密码和绑定新设备时触发短信二次验证。"
        "连续三次验证失败会临时锁定账号，二次验证记录保留在安全日志中。",
    },
    {
        "id": "export-audit",
        "text": "导出审计：所有客户与订单导出操作都会记录操作人、条数和时间。"
        "导出包含敏感字段时需要管理员审批，审计记录保留一年且不可删除。",
    },
    {
        "id": "inventory-freeze",
        "text": "盘点冻结：月度盘点期间仓库冻结出入库操作，紧急出库需要仓库主管手工解锁。"
        "冻结期间产生的订单顺延到盘点结束后处理，盘点结果确认后自动解冻。",
    },
    {
        "id": "contract-template",
        "text": "合同模板：标准销售合同模板在资料中心下载，模板编号以 CT 开头。"
        "使用模板签署前需要法务确认条款版本，修改模板需要走变更审批。",
    },
    {
        "id": "onboarding-intern",
        "text": "实习生入职：实习生签订实习协议，实习期一般为六个月，不设试用期。"
        "实习转正需要部门负责人评估并提交转正申请，转正后重新签订劳动合同。",
    },
    {
        "id": "customer-tier-vip",
        "text": "VIP 客户服务：VIP 客户配备专属客户经理，享受七乘二十四小时响应。"
        "VIP 等级每年复核一次，未达标的客户降为普通客户并调整服务策略。",
    },
    {
        "id": "data-retention-legal",
        "text": "诉讼保留：涉及诉讼或监管调查的数据进入保留状态，暂停自动删除流程。"
        "保留状态需要法务发起并定期复核，案件结束后恢复常规保留策略。",
    },
    {
        "id": "print-template-barcode",
        "text": "条码打印：条码打印失败先检查打印机分辨率与碳带余量，再重新下发打印任务。"
        "条码内容重复会导致校验失败，需要在模板中确认序列号规则。",
    },
]

QUERIES: list[dict[str, object]] = [
    {"q": "客户想退款，几天内可以无理由退？", "expected": ["refund-policy", "refund-policy-vip"]},
    {"q": "Mac 怎么安装客户端？", "expected": "install-guide"},
    {"q": "开增值税专用发票要什么资料？", "expected": "invoice-rules"},
    {"q": "迟到半小时怎么算？", "expected": "attendance"},
    {"q": "客户一直没安装，订单算交付完成吗？", "expected": "delivery"},
    {"q": "普通员工能看哪些页面？", "expected": "permissions"},
    {"q": "数据库多久备份一次？", "expected": "backup"},
    {"q": "平台模型的密钥在哪里配置？", "expected": "model-config"},
    {"q": "五万以上的采购要谁审批？", "expected": "approval"},
    {"q": "订单导出成 Excel 在哪里下载？", "expected": "export"},
    {"q": "密码输错几次会被锁定？", "expected": "security"},
    {"q": "今天下午三点付款什么时候发货？", "expected": ["shipping", "shipping-holiday"]},
    {"q": "库存低于安全线会提醒吗？", "expected": "inventory"},
    {"q": "电子合同怎么确认身份？", "expected": "contract"},
    {"q": "新员工试用期多久，转正谁审批？", "expected": "onboarding"},
    {"q": "多大的客户算战略客户？", "expected": "customer-tier"},
    {"q": "质量问题退货的运费谁出？", "expected": "refund-freight"},
    {"q": "客户注销后多久删除数据？", "expected": "data-retention"},
    {"q": "接口超过每分钟三百次会怎样？", "expected": "api-limit"},
    {"q": "打印模板改完为什么不生效？", "expected": "print-template"},
    {"q": "出差住宿标准是多少？", "expected": "expense-reimburse"},
    {"q": "年假没休完可以转到下一年吗？", "expected": "leave-policy"},
    {"q": "新员工入职培训多久一次？", "expected": "training"},
    {"q": "采购一定要先找三家供应商比价吗？", "expected": "procurement"},
    {"q": "供应商准入需要哪些资质？", "expected": "supplier"},
    {"q": "来料抽检不合格怎么处理？", "expected": "quality"},
    {"q": "物流轨迹多久更新一次？", "expected": "logistics"},
    {"q": "整机保修期多长？", "expected": "warranty"},
    {"q": "订阅到期前会自动续费吗？", "expected": "subscription"},
    {"q": "个人数据会被共享给第三方吗？", "expected": "privacy"},
    {"q": "版本发布前需要哪些验证？", "expected": "release"},
    {"q": "手机端支持的 iOS 最低版本是多少？", "expected": "mobile"},
    {"q": "企业微信能直接登录吗？", "expected": "sso"},
    {"q": "消息通知可以按模块关闭吗？", "expected": "notification"},
    {"q": "附件存储空间有多大？", "expected": "storage"},
    {"q": "谁改了配置能查到吗？", "expected": "audit"},
    {"q": "给客户报价走什么流程？", "expected": "pricing"},
    {"q": "可以按客户需求定制功能吗？", "expected": "customization"},
    {"q": "服务不可用有赔偿吗？", "expected": "sla"},
    {"q": "员工离职后账号怎么处理？", "expected": "offboarding"},
    {"q": "退款原路退回要几个工作日？", "expected": "refund-policy"},
    {"q": "发票开错了可以重开吗？", "expected": ["invoice-rules", "invoice-red"]},
    {"q": "补卡一个月最多几次？", "expected": "attendance"},
    {"q": "备份文件能恢复到昨天吗？", "expected": "backup"},
    {"q": "超过五万元的采购审批要几天？", "expected": "approval"},
    {"q": "导出的文件保留七天吗？", "expected": "export"},
    {"q": "异地登录需要二次验证吗？", "expected": ["security", "security-2fa"]},
    {"q": "预售商品什么时候发出？", "expected": "shipping"},
    {"q": "盘点差异需要谁确认？", "expected": "inventory"},
    {"q": "合同变更需要双方重新签署吗？", "expected": "contract"},
    {"q": "普通客户的退款期限是多久？", "expected": "refund-policy"},
    {"q": "VIP 客户退款期限和普通客户一样吗？", "expected": "refund-policy-vip"},
    {"q": "五千元以下的采购由谁审批？", "expected": "approval-small"},
    {"q": "五万元以上的采购是几级审批？", "expected": "approval"},
    {"q": "访客账号可以编辑页面吗？", "expected": "permissions-guest"},
    {"q": "异地备份多久做一次？", "expected": "backup-offsite"},
    {"q": "节假日期间的订单什么时候发货？", "expected": "shipping-holiday"},
    {"q": "发票红冲需要客户提供什么？", "expected": "invoice-red"},
    {"q": "外勤打卡需要上传照片吗？", "expected": "attendance-remote"},
    {"q": "什么情况下会触发二次验证？", "expected": "security-2fa"},
    {"q": "导出敏感字段需要审批吗？", "expected": "export-audit"},
    {"q": "盘点冻结期间能紧急出库吗？", "expected": "inventory-freeze"},
    {"q": "标准销售合同模板在哪里下载？", "expected": "contract-template"},
    {"q": "实习生有试用期吗？", "expected": "onboarding-intern"},
    {"q": "VIP 客户有专属客户经理吗？", "expected": "customer-tier-vip"},
    {"q": "涉及诉讼的数据还会自动删除吗？", "expected": "data-retention-legal"},
    {"q": "条码打印失败先检查什么？", "expected": "print-template-barcode"},
    {"q": "退款审批由谁确认？", "expected": "refund-policy"},
    {"q": "异地登录需要短信验证吗？", "expected": "security-2fa"},
]


OOD_QUERIES: list[str] = [
    "今天天气怎么样",
    "红烧肉怎么做",
    "推荐一部电影",
    "股票明天会涨吗",
    "帮我写一首诗",
    "量子力学是什么",
    "北京到上海多远",
    "如何减肥",
    "世界杯冠军是谁",
    "怎么学吉他",
    "我想订一张机票",
    "明天会下雨吗",
]


def _build_service(storage: Path):
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    return DatasetRagApplicationService(
        storage_path=storage,
        rebuild_workers_enabled=False,
    )


def run(*, rerank: bool, multi: bool = False, mmr_lambda: float = 0.0) -> dict[str, float]:
    from app.infrastructure.llm.embedding_service import get_default_embedding_service

    svc = get_default_embedding_service()
    mode = svc.mode if svc else "disabled"
    dataset_ids = ["eval-0", "eval-1", "eval-2"] if multi else ["eval"]
    with tempfile.TemporaryDirectory(prefix="kb-eval-") as tmp:
        service = _build_service(Path(tmp) / "datasets")
        for index, doc in enumerate(DOCS):
            service.ingest_document(
                dataset_id=dataset_ids[index % len(dataset_ids)] if multi else "eval",
                document_id=doc["id"],
                source=doc["id"],
                text=doc["text"],
                chunk_strategy="fixed",
                chunk_size=200,
                chunk_overlap=20,
            )
        hits_at = {1: 0, 3: 0, 5: 0}
        reciprocal = 0.0
        grounded = 0
        distinct_docs = 0
        for item in QUERIES:
            if multi:
                result = service.multi_query(
                    dataset_ids=dataset_ids,
                    query=str(item["q"]),
                    top_k=5,
                    rerank=rerank,
                    mmr_lambda=mmr_lambda,
                )
            else:
                result = service.query(
                    dataset_id="eval",
                    query=str(item["q"]),
                    top_k=5,
                    rerank=rerank,
                    mmr_lambda=mmr_lambda,
                )
            doc_ids = [
                str((chunk.get("metadata") or {}).get("document_id") or "")
                for chunk in result.get("chunks") or []
            ]
            distinct_docs += len(set(doc_ids))
            expected = item["expected"]
            expected_ids = {
                str(value) for value in (expected if isinstance(expected, list) else [expected])
            }
            rank = next((idx for idx, doc_id in enumerate(doc_ids, 1) if doc_id in expected_ids), 0)
            for k in hits_at:
                if rank and rank <= k:
                    hits_at[k] += 1
            reciprocal += 1.0 / rank if rank else 0.0
            if result.get("answer_grounded"):
                grounded += 1
        total = len(QUERIES)
        metrics = {
            "embedding_mode": mode,
            "datasets": len(dataset_ids),
            "queries": total,
            "recall@1": round(hits_at[1] / total, 4),
            "recall@3": round(hits_at[3] / total, 4),
            "recall@5": round(hits_at[5] / total, 4),
            "mrr": round(reciprocal / total, 4),
            "answer_grounded_rate": round(grounded / total, 4),
            "mmr_lambda": mmr_lambda,
            "distinct_doc_rate@5": round(distinct_docs / (total * 5), 4),
        }
        return metrics


def run_ood(*, multi: bool = False) -> dict[str, float]:
    """Out-of-domain queries must be refused instead of answered from noise."""
    from app.infrastructure.llm.embedding_service import get_default_embedding_service

    svc = get_default_embedding_service()
    mode = svc.mode if svc else "disabled"
    dataset_ids = ["eval-0", "eval-1", "eval-2"] if multi else ["eval"]
    with tempfile.TemporaryDirectory(prefix="kb-ood-") as tmp:
        service = _build_service(Path(tmp) / "datasets")
        for index, doc in enumerate(DOCS):
            service.ingest_document(
                dataset_id=dataset_ids[index % len(dataset_ids)] if multi else "eval",
                document_id=doc["id"],
                source=doc["id"],
                text=doc["text"],
                chunk_strategy="fixed",
                chunk_size=200,
                chunk_overlap=20,
            )
        answered = 0
        for query in OOD_QUERIES:
            if multi:
                result = service.multi_answer(dataset_ids=dataset_ids, query=query, top_k=5)
            else:
                result = service.answer(dataset_id="eval", query=query, top_k=5)
            if result.get("answer_grounded") is not False:
                answered += 1
        total = len(OOD_QUERIES)
        return {
            "embedding_mode": mode,
            "datasets": len(dataset_ids),
            "ood_queries": total,
            "ood_answered": answered,
            "ood_refused_rate": round((total - answered) / total, 4),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", action="store_true", help="启用精排（需 FHD_RERANK_* 配置）")
    parser.add_argument(
        "--multi", action="store_true", help="把文档拆到 3 个知识库并用 multi-query 融合检索"
    )
    parser.add_argument("--ood", action="store_true", help="只跑域外问题，检查是否被低置信拒答")
    parser.add_argument(
        "--diversity",
        type=float,
        default=0.0,
        metavar="LAMBDA",
        help="MMR 多样性权重 0–1（0 关闭）：同时报告 distinct_doc_rate@5",
    )
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()
    metrics = (
        run_ood(multi=args.multi)
        if args.ood
        else run(rerank=args.rerank, multi=args.multi, mmr_lambda=args.diversity)
    )
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False))
    else:
        print(f"知识库检索评测（{metrics['datasets']} 个知识库）")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
