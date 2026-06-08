# Skill: 发货单生成

## 能力描述
通过对话触发发货单生成，支持预览、确认与写库。

## 触发条件
- 用户在对话中请求生成发货单
- 微信消息命中发货类意图

## 执行步骤
1. 收集发货信息（客户、产品、数量）
2. 生成发货单预览
3. 用户确认后执行 shipment_generate 写库
4. 生成发货单文档

## 输入格式
```json
{
  "action": "shipment_generate",
  "customer": "客户名称",
  "items": [{"product": "产品A", "quantity": 10}]
}
```
