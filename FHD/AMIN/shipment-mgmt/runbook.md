# 出货管理 AI 员工运维手册

## 故障排查
- 发货单生成失败：检查 record_store 写入权限与数据库连接
- 打印失败：检查打印机连接与模板配置
- 审计数据不完整：检查出货记录 API 是否正常

## 关键信号
- xcagi:wechat-shipment-preview-task：微信触发的发货单预览任务
