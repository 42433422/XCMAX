# 微信消息处理 AI 员工运维手册

## 故障排查
- 消息轮询不工作：检查星标自动刷新开关与 work_mode_feed API
- 意图识别失败：检查 /api/ai/intent/test 接口或本地规则配置
- 任务列表未写入：检查 xcagi:wechat-ai-task-enqueue 信号派发

## 关键信号
- xcagi:wechat-ai-task-enqueue：微信 AI 任务入队信号
- xcagi:wechat-shipment-preview-task：发货单预览任务信号
