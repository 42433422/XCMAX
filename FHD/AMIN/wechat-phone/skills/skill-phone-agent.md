# Skill: 电话代理管理

## 能力描述
管理 phone-agent 服务的启动、停止与状态轮询。

## 触发条件
- 副窗启用/禁用本员工
- 定时轮询运行状态

## 执行步骤
1. 启用时 POST /api/mod/{mod_id}/phone-agent/start
2. 禁用时 POST /api/mod/{mod_id}/phone-agent/stop
3. 启用后约每 15s GET /api/mod/{mod_id}/phone-agent/status
4. 将 status 数据合并进工作流条目

## 输入格式
```json
{
  "action": "start|stop|status",
  "mod_id": "sz-qsm-pro"
}
```
