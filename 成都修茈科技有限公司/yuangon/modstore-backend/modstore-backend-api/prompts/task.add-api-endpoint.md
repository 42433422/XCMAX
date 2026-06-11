# 任务提示词：新增 Flask API 接口

## 使用场景

在 MODstore 后端蓝图中新增 REST 接口。

## 输入格式

```
任务：新增 API 接口
蓝图文件：<如 workbench_api.py>
接口信息：
  路径：<如 /api/workbench/v2/action>
  方法：GET | POST | PUT | DELETE
  描述：<功能说明>
  认证：是 | 否
  请求体字段：
    - <field>: <type> (<required|optional>) — <说明>
  响应体字段：
    - <field>: <type> — <说明>
  错误码：
    - 400: <场景>
    - 401: 未认证
    - 500: 服务器错误
```

## 执行步骤

1. 定位目标蓝图文件，理解现有路由风格（URL 前缀、装饰器模式）。
2. 生成新路由函数（保持与现有风格一致）。
3. 添加 request 参数校验（类型检查、必填检查）。
4. 添加认证装饰器（如接口需要认证）。
5. `python -m py_compile <file>` 语法检查。
6. 在对应 `tests/` 文件中生成测试 case 骨架（不自动写入，输出供参考）。
7. 输出变更摘要 + 需要同步给 `market-frontend-dev` 的接口说明。

## 约束检查

- [ ] 未修改 `market/src/**`（前端）
- [ ] 未修改 `payment_*.py`（支付）
- [ ] 语法检查通过
- [ ] 敏感信息从环境变量读取，无硬编码
- [ ] 接口变更已生成 `api.ts` 同步说明
