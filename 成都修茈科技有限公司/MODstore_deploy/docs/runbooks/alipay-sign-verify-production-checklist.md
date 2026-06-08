# 生产环境支付宝验签失败核对清单（查单 + 异步通知）

本文档对应一次线上排查结论：**「同步查单 `sign check fail`」与「异步通知验签失败」同源**，均为服务端用于验签的 **支付宝 RSA2 公钥** 与当前应用（`APP_ID` + 正式/沙箱网关）不匹配，或误填「应用公钥」。

## 1. 线上取证摘要（示例：`modstore_deploy-payment-service-1`）

### 1.1 日志特征

- **查单对账**：`AlipayApiException: sign check fail: check Sign and Data Fail!`（SDK 校验网关同步响应）。
- **异步通知**：`收到支付宝通知 …` 后立即 `支付宝通知验签失败`（`AlipaySignature.rsaCheckV1`）。

二者同时出现时，优先排查 **密钥三元组**，而非 Nginx。

### 1.2 运行时环境（容器内）

建议在服务器执行（**勿将私钥/公钥全文粘贴到聊天或工单**）：

```bash
docker logs modstore_deploy-payment-service-1 --tail 150
docker exec modstore_deploy-payment-service-1 printenv ALIPAY_APP_ID ALIPAY_DEBUG ALIPAY_GATEWAY_URL ALIPAY_NOTIFY_URL
docker exec modstore_deploy-payment-service-1 sh -c \
  'echo pub_len=${#ALIPAY_PUBLIC_KEY} alipay_pub_len=${#ALIPAY_ALIPAY_PUBLIC_KEY} priv_len=${#ALIPAY_PRIVATE_KEY}'
```

一次真实排查样例（脱敏）：

| 项 | 值 |
|----|-----|
| `ALIPAY_APP_ID` | `2021006146622799` |
| `ALIPAY_DEBUG` | `0`（走正式网关 `https://openapi.alipay.com/gateway.do`） |
| `ALIPAY_GATEWAY_URL` | 空（由 `AlipayConfig` 按 debug 选择网关） |
| `ALIPAY_NOTIFY_URL` | `https://xiu-ci.com/api/payment/notify/alipay` |
| 公钥两变量长度 | `ALIPAY_PUBLIC_KEY` 与 `ALIPAY_ALIPAY_PUBLIC_KEY` 均为 **392**（内容通常为同一串） |
| 私钥两变量长度 | `ALIPAY_PRIVATE_KEY` 与 `ALIPAY_APP_PRIVATE_KEY` 均为 **1624** |

说明：`application.yml` 中 `alipay.public-key` 解析顺序为 **`ALIPAY_PUBLIC_KEY` 优先于 `ALIPAY_ALIPAY_PUBLIC_KEY`**。两个都配置时，以 **`ALIPAY_PUBLIC_KEY`** 为准。

## 2. 开放平台核对（密钥三元组）

在支付宝开放平台打开 **同一应用**（与 `ALIPAY_APP_ID` 一致）：

1. **接口加签方式**：RSA2。
2. **应用私钥**：仅部署在服务器，与开放平台「应用公钥」配对；**不要把应用私钥发给他人**。
3. **支付宝公钥**：页面上的 **「支付宝公钥」**（平台生成），用于 SDK 验签；**绝不是「应用公钥」**。

将开放平台展示的 **支付宝公钥**（RSA2）配置到环境变量：

- 推荐只保留一类命名，避免重复冲突：例如仅设置 `ALIPAY_ALIPAY_PUBLIC_KEY`，并 **删除或清空** `ALIPAY_PUBLIC_KEY`（若曾填错，会继续覆盖正确值）。
- 密钥可为 PEM 单行 base64；`AlipayConfig.normalizeAlipayKey` 会去掉 PEM 头尾与空白。

### 沙箱 / 正式一致性

| 环境 | `ALIPAY_DEBUG` | 网关 |
|------|----------------|------|
| 正式 | `0` / `false` | `https://openapi.alipay.com/gateway.do` |
| 沙箱 | `1` / `true` | `https://openapi-sandbox.dl.alipaydev.com/gateway.do`（或可配 `ALIPAY_GATEWAY_URL`） |

**沙箱 APP_ID + 沙箱支付宝公钥 + 沙箱应用私钥** 必须成套；正式同理。混用会导致两类验签同时失败。

## 3. Nginx / 异步通知（次要）

当前站点示例：`location ~ ^/(api|modstore)/` 与 `location /api/` 反代至后端（如 `127.0.0.1:9999`），由网关再到 Java payment。**若查单已稳定失败，说明问题在密钥而非通知链路**。仅在「查单已成功、仅通知失败」时再查：

- 通知 URL 是否落到 **同一套** payment 实例与环境变量；
- 是否对 `application/x-www-form-urlencoded` body 做了改写或错误编码。

Compose 参考路径（以容器 label 为准）：`com.docker.compose.project.config_files` 指向服务器上的 `docker-compose.yml`。

## 4. 修复后冒烟（smoke test）

1. 修改 `.env` 或 Compose 中 Alipay 相关变量后：
   ```bash
   cd /root/XCai/MODstore_deploy   # 以服务器实际路径为准
   docker compose --profile app up -d payment-service
   ```
2. 观察启动日志是否包含 `AlipayConfig` 打头的网关、`sandbox=`、`APP_ID` 前缀与公钥长度日志。
3. 下一笔测试订单：支付完成后在收银台触发 **带 `reconcile=true` 的订单查询**，日志中不应再出现 `sign check fail`。
4. 同一笔订单应出现异步通知处理成功（或至少 **不再** `支付宝通知验签失败`）。

管理员可在登录后请求 `GET /api/payment/diagnostics`（经网关到 Java）查看 `alipay_async_notify` 片段（非管理员会隐藏 `effective_notify_url`）。

## 5. 代码引用（便于对照）

- Java 验签通知：`AlipayService.verifyNotify` → `AlipaySignature.rsaCheckV1(..., "RSA2")`
- Java 查单：`AlipayService.queryOrder` → `alipayClient.execute` 内同步响应验签
- 客户端 Bean：`AlipayConfig`（网关、`DefaultAlipayClient`、`RSA2`）
