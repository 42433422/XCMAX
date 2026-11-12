# Runbook：员工包质询员

## 触发

- 人工：在工作台对该员工执行自然语言任务，附上候选 `manifest` JSON 或同步测试失败日志。
- 自动化：工作流节点在 `validate_only` 之后插入本员工，仅消费结构化 `payload`。

## 升级路径

若结论为「有条件录用」，指派给 `employee-pack-curator` 修 manifest，再回跑同步测试。

## 回滚

本岗位为只读评审，无数据库写权限；回滚即忽略本次输出并恢复上一版 `.xcemp`。
