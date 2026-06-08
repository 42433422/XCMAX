# MODstore 单机灾备与恢复 Runbook

## 目标

当前目标是单机/少量服务器可恢复，而不承诺真正多活。默认恢复目标：

- RPO：核心数据库 24 小时以内，支付高峰期建议 1 小时以内。
- RTO：单机故障 2 小时内恢复到备机或新机器。
- 优先级：PostgreSQL > `modstore_data` > Redis/RabbitMQ > Grafana/Prometheus。

## 备份

在 `MODstore_deploy` 目录运行：

```bash
python scripts/backup_modstore.py
```

可只备份部分组件：

```bash
python scripts/backup_modstore.py --components postgres,redis,modstore_data
```

默认输出到 `backups/<UTC timestamp>/`，包含：

- `postgres.dump`：PostgreSQL custom dump。
- `redis-data.tar.gz`：Redis AOF/RDB 数据目录。
- `rabbitmq-data.tar.gz`：RabbitMQ 数据目录。
- `modstore-data.tar.gz`：FastAPI `/data`，含 webhook 事件、支付订单、向量库等。
- `prometheus-data.tar.gz`、`grafana-data.tar.gz`：监控数据。
- `manifest.json`：备份清单和文件大小。

建议把备份目录同步到备机或对象存储，不要只保存在业务主机本地。

## PostgreSQL 恢复

先确认目标数据库、环境变量和连接信息正确，再 dry-run：

```bash
python scripts/restore_postgres.py backups/20260101T000000Z/postgres.dump
```

确认无误后执行：

```bash
python scripts/restore_postgres.py backups/20260101T000000Z/postgres.dump --confirm
```

如需覆盖已有对象：

```bash
python scripts/restore_postgres.py backups/20260101T000000Z/postgres.dump --confirm --clean
```

恢复后执行：

```bash
python scripts/sre_smoke_check.py \
  --base-url http://127.0.0.1:8765 \
  --market-url http://127.0.0.1:4173 \
  --payment-url http://127.0.0.1:8080 \
  --prometheus-url http://127.0.0.1:9090
```

## 整机故障切换

1. 在备机安装 Docker、Docker Compose、Git 和运行所需密钥。
2. 拉取同一版本代码，复制 `.env` 和证书。
3. 同步最新备份目录到备机。
4. 启动基础设施：`docker compose up -d postgres redis rabbitmq`。
5. 恢复 PostgreSQL，必要时恢复 Redis/RabbitMQ/`modstore_data` tar 包。
6. 启动业务：`docker compose --profile app up -d --build`。
7. 执行冒烟检查和支付灰度预检。
8. 通过 DNS、Nginx 或云解析把流量切到备机。

## 常见事故

| 事故 | 止血动作 | 恢复动作 |
| --- | --- | --- |
| 数据库损坏 | 停止写入入口，保留现场 | 用最近 `postgres.dump` 恢复到新实例 |
| 误删业务数据 | 暂停相关写入，确认时间点 | 从备份恢复到临时库，人工比对补偿 |
| Redis 损坏 | 重启 Redis，允许缓存重建 | 必要时恢复 `redis-data.tar.gz` |
| RabbitMQ 损坏 | 暂停依赖队列的功能 | 恢复数据目录或清空重建，确认业务幂等 |
| 支付切换失败 | 按 `PAYMENT_GRAY_RELEASE.md` 回滚 | 对 Java 期间订单做人工核对 |
| 前端发布失败 | 回滚静态产物或镜像 | 执行 market workflow 前后冒烟 |

## 多活目标态

真正多活需要托管数据库或跨区复制、对象存储、全局流量调度、幂等事件、跨区一致性和自动化故障转移。当前阶段只建设冷备/温备和定期恢复演练。
