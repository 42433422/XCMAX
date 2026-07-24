# 闭环缺口

- 智能对话：会话可读，但发消息接口 /api/chat/send 与 /messages 返回 405（Method Not Allowed）——对话写入闭环未通
- 知识库：页面入口在，专用 /api/persy/knowledge、/api/knowledge 404；仅 office-pack status 可用
- 员工工作台：核心员工 Mod status 可用；overview/employees 列表 API 404
- 组织管理：创建返回成功，但随后列表 count 未增长/未按 code 找回（读写一致性存疑）
- 业务对象：创建产品后列表可见（产品闭环通）
- 资源库：创建物料成功（物料闭环通）
- 打印机列表：检测到 Canon_TS3700_series 就绪
- 模板与打印：模板列表 API 通但 templates 为空
