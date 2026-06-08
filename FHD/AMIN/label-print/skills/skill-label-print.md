# Skill: 标签打印

## 能力描述
从星标微信消息中识别打印意图，在对话中收集打印参数并执行打印。

## 触发条件
- 星标微信消息命中「标签/打印」意图关键词
- 用户在对话中主动请求打印

## 执行步骤
1. 接收 xcagi:workflow-label-print-signal 信号
2. 在对话中引导用户补充型号、张数、模板等参数
3. 调用打印 API 执行打印链路
4. 返回打印结果与状态

## 输入格式
```json
{
  "action": "print",
  "model": "产品型号",
  "quantity": 1,
  "template": "模板名称"
}
```

## 输出格式
```json
{
  "status": "success|failed",
  "message": "打印结果描述",
  "print_job_id": "任务ID"
}
```
