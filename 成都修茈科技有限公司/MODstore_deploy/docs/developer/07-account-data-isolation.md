# 多账号数据是否隔离

本文说明 MODstore 中「每个登录账号的业务数据」如何在存储与接口层分开，以及哪些资源在设计上为全站共享。

## 结论

**按用户维度是分开的**：钱包、订单、权益、配额、个人知识库归属等，在数据库中通过 `user_id`（或知识库 v2 的 `owner_kind` + `owner_id`）区分；HTTP 接口通过当前登录用户解析（`Authorization` → `get_current_user`）在查询中绑定 `user.id`，避免串号。

实现入口：`modstore_server/api/deps.py` 中的 `get_current_user` / `_get_current_user`。

## 数据库层

- **核心 schema**（Java 迁移脚本，与业务模型一致）：`java_payment_service/src/main/resources/db/migration/V1__modstore_core_schema.sql`
  - `wallets.user_id` 为 UNIQUE（一人一钱包）
  - `transactions`、`purchases` 等表含 `user_id` 外键
- **权益与配额**：`V2__wallet_finance_unification.sql` 中 `entitlements`、`user_plans`、`quotas` 均含 `user_id` 及面向用户的索引

## 接口层示例

- `modstore_server/payment_api.py` 中例如 `/my-plan`：`UserPlan.user_id == user.id`、`Quota.user_id == user.id`，仅返回当前用户的套餐与配额。

## 知识库 v2

- `modstore_server/knowledge_v2_api.py` 与 `modstore_server/rag_service.py` 的 `visible_collection_ids`：以 `("user", str(user_id))` 等为身份，叠加授权（`KnowledgeMembership`）与 `visibility='public'` 的集合；**不会把他人私有集合默认当作当前用户可见**。

## 与「domain isolation」测试的区别

`tests/test_domain_isolation.py` 中的「domain isolation」指**微服务/模块边界**（例如支付域不直接 import 通知域），**不是**「多租户/多账号数据隔离」的专项测试名。多账号隔离依赖：**schema 设计 + `Depends(get_current_user)` + 每条查询带上用户/所有者条件**。

## 设计上会共享的内容（预期行为）

- 市场 **公开** 商品/目录（如 `catalog_items` 的 `is_public` 等）：全站可见，非单账号独占。
- **管理员**路径通过 `require_admin` 等与普通用户区分，可具备更广查询范围。

如需核对某一具体模块（工作台会话、工作流、员工配置等），在对应 `*_api.py` 中逐项检查是否所有读写都带 `user.id` 或 `owner` 条件。
