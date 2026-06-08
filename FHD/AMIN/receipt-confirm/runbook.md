# 收货确认 AI 员工运维手册

## 故障排查
- 收货信号未触发：检查星标消息轮询与 isReceiptConfirmRelatedWechatIntent 规则
- 工作流条目未写入：检查 workflowEmployeeSpace 桥接逻辑
- 对话跟进失败：检查对话上下文与客户数据

## 关键信号
- xcagi:workflow-receipt-feedback-signal：收货反馈信号
