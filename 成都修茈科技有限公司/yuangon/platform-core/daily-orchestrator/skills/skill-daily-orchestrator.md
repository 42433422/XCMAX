# 每日编排

- 优先修复 `MODstore_deploy/tests` 与 CI 可见失败；改动尽量小、可回滚。
- **禁止**修改 `modstore_server/models.py`、迁移文件、`*.db`、`catalog_data/`、`library/`。
- 不提交密钥；环境相关仅使用占位或文档说明。
