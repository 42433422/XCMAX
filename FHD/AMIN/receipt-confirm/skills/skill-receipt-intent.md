# Skill: 收货意图识别

## 能力描述
从星标微信消息中识别收货、到货、签收、对账等意图。

## 触发条件
- 星标微信消息命中收货相关意图关键词

## 执行步骤
1. 接收星标消息轮询结果
2. 运行 isReceiptConfirmRelatedWechatIntent 意图判断
3. 命中后派发 xcagi:workflow-receipt-feedback-signal
4. 将联系人及业务进程摘要写入工作流条目

## 输入格式
```json
{
  "action": "signal",
  "signal_type": "workflow-receipt-feedback-signal",
  "contact": "客户名称",
  "intent": "receipt_confirm"
}
```
