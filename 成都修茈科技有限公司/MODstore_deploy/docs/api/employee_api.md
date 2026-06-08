# employee_api

员工API模块，提供员工相关的API端点。

## GET /api/employees/

**说明**: 获取员工列表

获取所有可用的AI员工。

参数：无

响应示例：
```json
[
  {
    "id": "employee_id",
    "name": "Employee Name"
  }
]
```

## GET /api/employees/{employee_id}/status

**说明**: 获取员工状态

获取员工的状态信息。

参数：
- `employee_id` (str): 员工ID

响应示例：
```json
{
  "status": "active",
  "details": {}
}
```

## POST /api/employees/{employee_id}/execute

**说明**: 执行员工任务

执行员工任务。

参数：
- `employee_id` (str): 员工ID
- `task` (str): 任务描述
- `input_data` (Optional[Dict]): 输入数据，默认为None

响应示例：
```json
{
  "status": "success",
  "result": {}
}
```