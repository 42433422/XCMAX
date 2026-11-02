# 开发规范

## 代码规范

### Python 代码规范

1. **格式化**
   - 使用 `Ruff` 格式化所有 Python 代码，使用 Ruff 的 `I` 规则排序 imports
   - 检查命令：`uv run ruff check app/ tests/` 与 `uv run ruff format --check app/ tests/`

2. **类型检查**
   - 使用 `mypy` 进行类型检查：`uv run mypy app/ --no-error-summary`
   - 所有新增公共函数应有类型注解，历史豁免需逐步清偿

3. **代码风格**
   - 遵循 PEP 8
   - Ruff `line-length = 100`；超过 100 字符由格式化器和 lint 规则共同管理

4. **导入顺序**
   ```python
   # 标准库
   import os
   import sys

   # 第三方库
   from fastapi import APIRouter
   from sqlalchemy.orm import Session

   # 本地库
   from app.application.auth_app_service import get_auth_app_service
   ```

### JavaScript 代码规范

1. **格式化**
   - 使用 Prettier 格式化代码
   - 使用 ESLint 检查代码

2. **代码风格**
   - 使用 ES6+ 语法
   - 使用 const/let 而不是 var

### 后端验证

- 使用 `uv run pytest tests/ -q` 执行完整后端回归测试。
- PR 的架构检查、类型检查、行为测试和覆盖率棘轮以仓根 `/.github/workflows/fhd-ci-cd.yml` 为准。
- 测试膨胀检测发现历史基线缺失时应失败；仅由维护者明确使用 `--seed` 初始化。
- 超过 800 行的历史文件仍需逐步拆分；已登记的单文件行数限额不得调高，未经批准不得使用 `--force` 提高基线。

## Git 规范

### 分支命名
- `feature/xxx` - 新功能
- `fix/xxx` - Bug 修复
- `refactor/xxx` - 重构
- `docs/xxx` - 文档更新

### Commit 规范
```
<type>(<scope>): <subject>

<body>

<footer>
```

类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档
- `style`: 格式
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具

### 示例
```
feat(auth): 添加用户注册功能

添加用户注册功能，包括：
- 验证码发送
- 密码强度验证
- 邮箱验证

Closes #123
```

## 代码审查规范

### Review 清单
- [ ] 代码符合规范
- [ ] 有适当的测试
- [ ] 没有明显的 bug
- [ ] 注释清晰完整
- [ ] 性能考虑
- [ ] 安全性考虑

### Review 流程
1. 创建 Pull Request
2. 至少 1 人 Review
3. 所有问题解决
4. 合并到主分支
