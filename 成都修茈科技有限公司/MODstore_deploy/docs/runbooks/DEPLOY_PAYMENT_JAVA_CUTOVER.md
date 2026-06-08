# 生产直切 PAYMENT_BACKEND=java（执行清单）

代码与脚本已就绪；**在服务器上按序执行**（本机无法 SSH 时请用 `unified-deploy.ps1` / `sync-modstore-to-server.ps1` 同步后 SSH 登录执行）。

## 0. 同步代码到生产

```powershell
# 本机（示例）
.\scripts\unified-deploy.ps1 -Mode FullSync -SshTarget root@119.27.178.147
```

服务器需包含：

- `modstore_server/payment_health_api.py` → `GET /api/health/payment`
- `scripts/production_flip_payment_backend_java.sh`
- `docker-compose.yml`（`api` 依赖 `payment-service`）

## 1. 预检（仍可为 `PAYMENT_BACKEND=python`）

```bash
cd /root/modstore-git/MODstore_deploy   # 按实际路径调整
cp .env .env.bak.$(date -u +%Y%m%dT%H%M%SZ)
./scripts/production_flip_payment_backend_java.sh preflight
NOTIFY_URL=https://xiu-ci.com/api/payment/notify/alipay ./scripts/verify_alipay_notify_route.sh
```

期望：

- `payment-service` 健康，`/actuator/health` → `UP`
- `payment_gray_release_check.py` 全部 OK
- notify 探针非 502/503

## 2. 支付宝回调

确认 `.env` 中 `ALIPAY_NOTIFY_URL=https://xiu-ci.com/api/payment/notify/alipay`，且 Nginx `/api` 反代到 MODstore `:8765`（BFF 再代理到 Java）。

切换窗口前用沙箱或最小金额验证 notify 返回 `success`。

## 3. 直切

```bash
DRAIN_SECONDS=60 ./scripts/production_flip_payment_backend_java.sh flip
```

验证：

```bash
curl -s http://127.0.0.1:8765/api/health/payment | python3 -m json.tool
# payment_backend=java, java_service_healthy=true

curl -s https://xiu-ci.com/api/health/payment | python3 -m json.tool
curl -s https://xiu-ci.com/api/payment/plans | head
```

FHD（`/opt/fhd-full` 或实际路径）确认：

- `MODEL_PAYMENT_BACKEND=modstore`
- `XCAGI_MARKET_BASE_URL=https://xiu-ci.com`
- `XCAGI_MARKET_INTERNAL_API_KEY` 与 MODstore `MODSTORE_INTERNAL_API_KEY` 一致

`curl -s https://xiu-ci.com/api/operations-line/health`（FHD）→ `steps.O4.note` 含「市场支付已切 Java SoT」。

## 4. 回滚

```bash
./scripts/production_flip_payment_backend_java.sh rollback
```

详见 [PAYMENT_GRAY_RELEASE.md](../PAYMENT_GRAY_RELEASE.md) §4。
