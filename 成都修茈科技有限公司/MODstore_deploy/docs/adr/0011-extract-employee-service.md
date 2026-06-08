# ADR 0011：抽出独立 Employee 服务评估

## 状态

提议

## 背景

`EmployeeRuntimeClient` 封装 `employee_executor`；执行链路与 `EmployeeExecutionMetric` 紧耦合 PostgreSQL。

## 决策（草案）

- **表面 API**：`list_employees` / `get_employee_status` / `execute_task` 不变；增加异步 job id 可选扩展。
- **配置**：`MODSTORE_EMPLOYEE_SERVICE_URL`；大 payload 走对象存储预签名 URL。
- **HttpEmployeeRuntimeClient**：包装为多部分 REST；错误模型与现有 JSON 对齐。
- **回滚**：`set_default_employee_client(InProcessEmployeeRuntimeClient())`。
- **灰度**：按 Mod / 租户切流；与 `employee.pack_registered` 事件对齐观测。

## 后果

- 需迁移或共享 `CatalogItem(artifact=employee_pack)` 读取路径（可用现有 `CatalogClient`）。
