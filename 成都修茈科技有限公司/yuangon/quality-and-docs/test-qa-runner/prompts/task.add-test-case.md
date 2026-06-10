# 任务提示词：补充测试用例

## 使用场景

当覆盖率不足、新增功能缺少测试、或 ESkill 动态阶段发现测试空白时使用。

## 输入格式

```
任务：补充测试用例
目标模块：<如 MODstore_deploy/modstore_server/workbench_api.py>
测试文件：<如 MODstore_deploy/tests/test_workbench.py>
需要覆盖的场景：
  - 场景 1：<描述>
  - 场景 2：<描述>
测试类型：unit | integration
```

## 执行步骤

1. 阅读目标模块的函数/路由签名和现有测试。
2. 识别未覆盖的分支（happy path / error path / edge case）。
3. 生成测试用例（pytest 风格，使用现有 fixture 约定）。
4. 运行 `python -m pytest <test_file> -v` 确认通过。
5. 重新生成覆盖率，确认阈值达标。

## 约束检查

- [ ] 只在 `tests/**` 下添加文件，不改源码
- [ ] 遵循现有 fixture 和命名约定
- [ ] 新测试通过且不破坏现有测试
- [ ] 覆盖率达到目标阈值
