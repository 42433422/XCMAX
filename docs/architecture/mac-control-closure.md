# Mac 主控协同：实现与启用契约

Mac 保持 Para 主控，服务器持久保存受理、派发关联及回执。Para 是执行状态来源，客户工单、授权及交付回执仍是业务来源。新功能默认关闭。

## 接口与持久记录

- 现有 `/api/admin/codex-super-employee/messages` 接受可选 `durable_request`，经管理会话代理到 MODstore。
- `/api/admin/mac-control/tasks` 受理或读取任务；`tasks/{id}` 支持 `after` 事件游标；`cancel` 不删除 Para 任务。
- `/api/admin/mac-control/fleet` 返回带观测时间的设备快照；`facts` 关联现有工单及标准交付来源。
- `/api/internal/mac-control/receipts` 使用按设备配置的服务身份，验证任务、设备、事件摘要和生产尝试。迟到回执保留历史，不修改执行状态。
- 新表 `mac_control_tasks/events/observations/sync_lease` 使用 MODstore 的同一数据库；现有 `init_db` 创建新表。升级保留旧表及业务数据，回滚禁止删除这些新记录。

## 发布开关

服务器配置：

| 配置 | 含义 |
|---|---|
| `MODSTORE_MAC_CONTROL_ENABLED=1` | 启用持久受理和后台同步；默认关闭 |
| `MODSTORE_MAC_CONTROL_EMPLOYEE_DISPATCH=1` | 将现有员工派工切换至相同适配层，必须在单任务验收后启用 |
| `MODSTORE_PARA_API_BASE` | 现有服务器到 Mac 的 Para 隧道入口 |
| `MODSTORE_PARA_AUTH_TOKEN` | 专用服务身份；新适配层禁止 guest 登录兜底 |
| `MODSTORE_PARA_DEVICE_ID` | Mac 首选设备，不强制覆盖 Windows 目标 |
| `MODSTORE_PARA_REPO_URL` | 允许的工厂仓库，缺失时不能执行 |
| `MODSTORE_MAC_CONTROL_DEVICE_TOKENS` | 设备 ID 到随机回执凭证的映射，仅放服务环境文件 |

Mac 代理配置 `XCMAX_CONTROL_RECEIPT_URL`、`XCMAX_CONTROL_RECEIPT_TOKEN`、`XCMAX_CONTROL_DEVICE_ID`；可用 `XCMAX_CONTROL_RECEIPT_DIR` 指定持久磁盘目录。禁止把凭证写入命令日志、知识库或 Git。

代理安装器同时安装工具预检和回执补传模块。仅从已合并主线提交安装；升级前确认代理无在途任务，保留备份与待回传目录。

## 恢复与执行约束

服务器每 15 秒同步；90 秒未观测则标记过期。数据库租约串行化派发，同一设备只保留一个未终结的修改任务。首次派发前提交尝试编号，响应丢失时按稳定任务标识查 Para，结果未知不重新提交。

CLI 必须通过新鲜的启动预检；历史代理没有该能力时显示等待。`--version` 只证明可启动，不证明账号额度或模型调用成功，真实执行仍单独验证。

Para 当前删除接口不能证明执行器停止；运行任务的取消保留为 `cancel_requested`，等待 Para 的真实终态，不能称为已取消。

新任务禁用自动合并，默认只读分析。开发模式的产物仍须经过现有审批、主线集成和发布门禁。生产及灾备节点展示已有桥接事实，不能误当成安装了编程 CLI 的开发设备。

## 验收与待衔接边界

必须验证：重复请求、响应丢失、服务重启、设备忙碌、预检缺失、非法身份、乱序及重复回执、窗口刷新、断网补传；任务完成不能改写客户交付。

以下不可从本地测试推断完成：生产服务身份及设备归属配置、Windows 原生代理预检回传兼容、Mac 到 Windows 的实际产物交接、真实断线恢复、审批至主线发布关联、客户安装及业务验收。

另一个活跃 `codex/ai-full-control` 分支的定时执行改动不在本次范围。实现不自动切换主控，也不覆盖其他活跃工作区。
