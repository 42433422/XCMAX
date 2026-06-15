# 任务提示词：调试 API 错误

## 使用场景

某个 MODstore API 接口出现异常（5xx、超时、数据格式错误）时使用。

## 输入格式

```
任务：调试 API 错误
接口：<路径，如 POST /api/workbench/v2/execute>
错误现象：<如 500 Internal Server Error>
错误信息/traceback：
  <粘贴 traceback 或错误日志>
复现步骤：
  1. <步骤一>
  2. <步骤二>
相关文件：<推测的源文件，如 workbench_api.py>
```

## 执行步骤

1. 解析 traceback，定位错误行和类型。
2. 读取相关源文件，理解上下文。
3. 分析根因（类型错误/空值/超时/权限）。
4. 生成最小修复 diff。
5. `python -m py_compile <file>` + 相关测试验证。
6. 输出：根因分析 + 修复方案 + 预防措施。

## 约束检查

- [ ] 修复范围不超过 `scope_globs`
- [ ] 不修改支付/前端/密钥文件
- [ ] 修复后测试通过
- [ ] 根因明确（不猜测）
