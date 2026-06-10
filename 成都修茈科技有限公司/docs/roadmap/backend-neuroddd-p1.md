# Backend NeuroDDD P1

目标：让新功能进入明确分层，旧 API 模块逐步变薄。

目标层级：

- `modstore_server/api/`：FastAPI composition、deps、schemas。
- `modstore_server/application/`：用例编排。
- `modstore_server/domain/`：领域 DTO、规则与 NeuroDomain 边界。
- `modstore_server/infrastructure/`：DB、文件、外部服务与 repository。
- `modstore_server/eventing/`：NeuroBus、事件 envelope、outbox。

已落地：

- 共享认证依赖：`modstore_server/api/deps.py`
- DB session：`modstore_server/infrastructure/db.py`
- 首批 application service：Auth、Catalog、Employee、Workflow、Notification、PaymentGateway、Analytics
- 边界测试：`MODstore_deploy/tests/test_neuro_ddd_boundaries.py`

P1 规则：

- domain 层不得导入 FastAPI、SQLAlchemy、httpx。
- 旧 API 模块不得重新实现 `_get_current_user`、`_require_admin` 或 `get_db`。
- 新的业务编排优先进入 application 层。
