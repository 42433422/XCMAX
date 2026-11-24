# 小 C 功能性元认知：独立离线研究

本目录仅供人工主持的离线对照评估，不接入运行时、预算、模型调用、发布或自我修改。不是意识证明、生产验收或正式能力分。

- 基线：#3533（冻结于 1dc75dbc），沿用 #3398、#3512、#3449 的原评审治理，不新增权限。
- 评估协议参考 FHD/config/audit_benchmark_ssot.json 的独立留出任务及重复采样下限。100 个留出任务、100 个不同来源摘要和来源组、每任务 3 次重复是研究样本下限。四种证据条件各至少 10 个来源组且所有成对观察具有独立结果及置信度，才可标记待人工复核；这是本研究的覆盖要求，不是原 SSOT 的正式评分门禁。来源摘要/分组数量也不是语义独立性的证明。开发、验证、最终保留三分区必须在冻结协议中均有登记；同一来源、来源组或引用摘要跨任意分区即拒绝。最终报告仅处理保留集观察，缺开发集或验证集时保持 insufficient_evidence。三分区存在与摘要不重叠仅证明合同层约束，不代表验证集已实测、语义无泄漏或实际能力提升。
- 人工评审者在实验前冻结 Protocol（源码、模型、设置、两臂策略、独立验证器、来源/组、允许引用、独立预期策略、seed）。保存 fingerprint(protocol) 到评审记录，不允许从事后协议重新生成来冒充预登记。
- promptfoo 或现有独立评估器的真实运行输出须由人工控制的导出器转换为 Observation 和 Receipt。每臂同任务、同 seed、同模型设置；逐条 Observation 同时绑定对应策略版本、模型版本、设置 SHA 和实际输出 SHA。保留集答案只交给独立评审者，不能进入策略提示词。当前不提供自动运行器或生产 promptfoo 导出集成。
- Receipt.correct 是外部独立判定，None 代表未知；receipt_sha256 指向原始评估回执，observation_sha256 绑定完整观察，包含 protocol SHA。摘要一致性不证明外部回执真实、验证器独立、授权合法或数据无语义重复，评审者须在受控私有环境核验原件。
- 只使用非敏感的不透明任务 ID 和来源 SHA，不提交客户原件、私有策略正文、保留集答案或原始回执到公开仓库。原经营反思可由人工关联原回执，但经营成功不能替代认知正确率；目前未完成原反思/能力评估的正式持久化适配。
- Brier 分数和可靠性曲线复用 scikit-learn。未知结果、缺失置信度分别报告，不算成正确/错误；成对变化按条件分层；Brier 差值仅在两臂都具有真实标签和置信度的配对上计算，显式报告覆盖率。每条审计记录保留观察摘要与独立回执摘要的关联。这些是描述统计，非独立显著性或因果结论。报告只有 insufficient_evidence / pending_human_review，无通过、自动推广、策略更新或执行权限。GrowthBook 真实受控实验仍由独立审批主持，不在本目录实现。

## 复验

在独立 Python 3.11+ 环境安装 requirements.txt（直接依赖版本为本轮本地测试版本，非完整生产锁）。进入本目录：

    python -m pytest -q test_xiaoc_metacognition_eval.py
    python xiaoc_metacognition_eval.py protocol.json FROZEN_SHA256 observations.json receipts.json > report.json

JSON 文件格式以严格 Pydantic 合同为准。报告须关联原冻结协议、真实独立回执和人工复核记录，保存于授权私有评测位置；不得自动反馈至执行器。

本地隔离合成验证 24 passed / 0 skipped（Python 3.13.5，pytest -q -W error）；源码及测试 Git blob SHA 分别为 a249e75ceaa4ecb824602190d785d22dc442653b、6637fa793fa196523c9041ac155a1f6e6bcbb295。尚无真实小 C 保留任务、真实 promptfoo 双臂运行、反思持久化接线、完整仓库 preflight 或正式 CI 证据。保留 Draft。
