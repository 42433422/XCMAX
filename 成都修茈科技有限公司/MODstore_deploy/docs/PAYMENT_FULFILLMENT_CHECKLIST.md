# 支付履约验收清单（Python / Java）

## 配置矩阵

| 场景 | 履约权威 | 本地 `payment_orders` JSON |
|------|-----------|---------------------------|
| `PAYMENT_BACKEND=python`（默认） | FastAPI `_fulfill_paid_order` | 读写 |
| `PAYMENT_BACKEND=java` | `OrderService.fulfillOrder` + `EntitlementService` | 只读兜底，勿双写 |

## P0 验收项

1. **商品单（item）**  
   - DB：`Purchase`（若首次）、`Entitlement`（`source_order_id` 幂等）、员工包时 `entitlement_type=employee` 且 `employee_count` 配额 +1。  
   - Java：`grantCatalogEntitlement` 按 `CatalogItem.artifact == employee_pack` 区分 `employee` / `mod`，员工包递增 `employee_count`。

2. **套餐单（plan）**  
   - 停用旧 `UserPlan`，写入新 `UserPlan` + `Entitlement(plan)` + `Quota` 行；钱包随单赠送（与 Java 一致）。

3. **钱包充值（wallet）**  
   - `Transaction` 描述中包含 `(out_trade_no)`，用于 Python 侧幂等去重。

4. **异常路径**  
   - `user_id=0`：**不**标记 `fulfilled`，日志报错，待补用户后走 query 补履约。  
   - 重复回调：同一 `source_order_id` 或同一笔钱包 `Transaction` 描述 → 幂等跳过。

5. **可选自动部署（员工包）**  
   - `MODSTORE_AUTO_DEPLOY_XCAGI=1`：`zip` → Mod 库 → `deploy_to_xcagi`（与 `/api/sync/push` 相同 XCAGI 根配置）。

## 建议自动化测试

- Python：`tests/test_payment_*`、`tests/test_payment_notify_python.py`（`PAYMENT_BACKEND` 非 `java` 时支付宝回调 fallback）、`payment_orders` 幂等。  
- Java：`EntitlementServiceTest`（员工包 + quota）、`OrderServiceTest`。
