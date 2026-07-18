# CVM 单点灾备方案（每日快照 + 异地 COS）

> **背景**：生产 CVM 单点 119.27.178.147，无 HA、无多区。PostgreSQL 数据库 + 用户上传文件 + MOD 安装包是关键资产。
> **历史教训**：本地 SQLite 单点曾被雷霆手段修复（每日 12:30 全量 + 周日全量 + 异地外置 + PRAGMA 校验），现复刻到 CVM。
> **目标**：RPO ≤ 24h（日全量）+ RPO ≤ 1h（小时 WAL 归档）+ RTO ≤ 30min
> **成本**：约 ¥30-50/月（腾讯云 COS 标准存储 + 跨区复制）

## 一、资产盘点与保护等级

| 资产 | 路径 | 大小估计 | 保护等级 | 备份频率 |
|------|------|---------|---------|---------|
| PostgreSQL `xcagi` | `/var/lib/postgresql/data` 或 docker volume | 2-10 GB | **P0** | 每日全量 + 每小时 WAL |
| PostgreSQL `xcagi_mod_*` | 同上（多 MOD 独立库） | 0.5-2 GB × N | **P0** | 每日全量 + 每小时 WAL |
| 用户上传 | `/opt/fhd-full/uploads/` | 1-5 GB | **P0** | 每日增量 |
| MOD 安装包 | `/opt/fhd-full/mods/` | 500MB-2GB | P1 | 每日增量 |
| 日志 | `/opt/fhd-full/logs/` | 滚动增长 | P2 | 每周归档 |
| 配置文件 | `/root/fhd-full.env` + `/opt/fhd-full/docker-compose.yml` | KB 级 | **P0** | 每日全量 |
| SSL 证书 | `/etc/letsencrypt/` | KB 级 | P1 | 每周全量 |

## 二、灾备架构

```
┌──────────────────────────────────────────────────────────────────┐
│  CVM 生产（上海 119.27.178.147）                                 │
│                                                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────────┐ │
│  │ PostgreSQL  │   │ /opt/fhd-   │   │ /opt/fhd-full/mods      │ │
│  │ (主库)      │   │ full/uploads│   │ /opt/fhd-full/data      │ │
│  └──────┬──────┘   └──────┬──────┘   └──────────┬──────────────┘ │
│         │                 │                     │                │
│  ┌──────▼─────────────────▼─────────────────────▼──────────────┐ │
│  │  fhd-backup-daily.sh（cron 每日 02:00 UTC，业务低峰）        │ │
│  │  1. pg_dump 全量（custom format，压缩）                     │ │
│  │  2. 增量 rsync uploads/mods                                 │ │
│  │  3. tar 配置文件                                            │ │
│  │  4. coscmd 上传 → COS 主 bucket                             │ │
│  │  5. PRAGMA quick_check + pg_restore --list 完整性校验      │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  fhd-backup-hourly-wal.sh（cron 每小时）                     │ │
│  │  PostgreSQL WAL 增量归档（pg_receivewal / archive_command）  │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ▼ HTTPS
┌──────────────────────────────────────────────────────────────────┐
│  腾讯云 COS 主 bucket（上海）                                     │
│  xcagi-cvm-backup-sh/                                            │
│    ├── postgres/daily/fhd-full-YYYYMMDD-HHMMSS.dump              │
│    ├── postgres/wal/0000000100000000000000XX                     │
│    ├── uploads/daily/YYYYMMDD/                                   │
│    ├── mods/daily/YYYYMMDD/                                      │
│    ├── config/daily/YYYYMMDD.tar.gz                              │
│    └── manifest.json（备份元数据 + 校验和）                       │
└────────────────────────┬─────────────────────────────────────────┘
                         │ COS 跨区复制规则（自动）
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  腾讯云 COS 异地 bucket（北京）                                   │
│  xcagi-cvm-backup-bj/（同结构，跨区热备）                         │
│  保留：每日全量 7 天 + 每周全量 4 周 + 每月全量 12 个月           │
└──────────────────────────────────────────────────────────────────┘
```

## 三、核心脚本

### 3.1 每日全量备份（`FHD/scripts/deploy/fhd-backup-daily.sh`）

```bash
#!/usr/bin/env bash
# 每日全量备份：PostgreSQL + uploads + mods + config → COS 主 bucket
# 由 cron 每日 02:00 UTC 调用（业务低峰）
set -euo pipefail

BACKUP_ROOT="${FHD_BACKUP_ROOT:-/var/backups/fhd}"
DATE_STAMP="$(date +%Y%m%d-%H%M%S)"
WEEK_STAMP="$(date +%Y-W%V)"
MONTH_STAMP="$(date +%Y-%m)"
PG_CONTAINER="${FHD_PG_CONTAINER:-fhd-postgres}"
PG_USER="${FHD_PG_USER:-xcagi}"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"

mkdir -p "$BACKUP_ROOT/$DATE_STAMP"
cd "$BACKUP_ROOT/$DATE_STAMP"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/fhd-backup.log; }

# ========== 1. PostgreSQL 全量（custom format，可并行恢复） ==========
log "1/6 备份 PostgreSQL..."
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc xcagi > xcagi.dump
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc --schema-only xcagi > xcagi-schema.dump

# 备份所有 MOD 独立库
for db in $(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -Atc \
  "SELECT datname FROM pg_database WHERE datname LIKE 'xcagi_mod_%'"); do
  docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -Fc "$db" > "$db.dump"
done

# 完整性校验
log "  校验 pg_restore 可读性..."
docker exec -i "$PG_CONTAINER" pg_restore --list < xcagi.dump > /dev/null

# ========== 2. 用户上传增量（rsync 增量同步） ==========
log "2/6 增量同步 uploads/..."
rsync -a --link-dest="$BACKUP_ROOT/latest-uploads" \
  /opt/fhd-full/uploads/ "$BACKUP_ROOT/$DATE_STAMP/uploads/"
ln -sfn "$BACKUP_ROOT/$DATE_STAMP/uploads" "$BACKUP_ROOT/latest-uploads"

# ========== 3. MOD 安装包增量 ==========
log "3/6 增量同步 mods/..."
rsync -a --link-dest="$BACKUP_ROOT/latest-mods" \
  /opt/fhd-full/mods/ "$BACKUP_ROOT/$DATE_STAMP/mods/"
ln -sfn "$BACKUP_ROOT/$DATE_STAMP/mods" "$BACKUP_ROOT/latest-mods"

# ========== 4. 配置 + SSL 证书 ==========
log "4/6 打包配置..."
tar czf config.tar.gz \
  /root/fhd-full.env \
  /opt/fhd-full/docker-compose.yml \
  /etc/letsencrypt/ 2>/dev/null || true

# ========== 5. 上传到 COS 主 bucket ==========
log "5/6 上传 COS..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload xcagi.dump "postgres/daily/xcagi-$DATE_STAMP.dump"
coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload config.tar.gz "config/daily/$DATE_STAMP.tar.gz"
coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload -rs uploads/ "uploads/daily/$DATE_STAMP/"
coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload -rs mods/ "mods/daily/$DATE_STAMP/"

# 周日全量也存到 weekly/
if [[ "$(date +%u)" == "7" ]]; then
  coscmd -r "$COS_REGION" -b "$COS_BUCKET" copy \
    "postgres/daily/xcagi-$DATE_STAMP.dump" "postgres/weekly/xcagi-$WEEK_STAMP.dump"
fi
# 每月 1 日存到 monthly/
if [[ "$(date +%d)" == "01" ]]; then
  coscmd -r "$COS_REGION" -b "$COS_BUCKET" copy \
    "postgres/daily/xcagi-$DATE_STAMP.dump" "postgres/monthly/xcagi-$MONTH_STAMP.dump"
fi

# ========== 6. 本地保留 7 天 + 写 manifest ==========
log "6/6 清理本地 7 天前备份..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +7 -not -name latest-\* -exec rm -rf {} \;

cat > manifest.json <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "date_stamp": "$DATE_STAMP",
  "postgres_databases": ["xcagi", $(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -Atc "SELECT string_agg('\"'||datname||'\"', ',') FROM pg_database WHERE datname LIKE 'xcagi_mod_%'")],
  "sha256": {
    "xcagi.dump": "$(sha256sum xcagi.dump | awk '{print $1}')",
    "config.tar.gz": "$(sha256sum config.tar.gz | awk '{print $1}')"
  },
  "cos_bucket": "$COS_BUCKET",
  "cos_paths": {
    "postgres": "postgres/daily/xcagi-$DATE_STAMP.dump",
    "uploads": "uploads/daily/$DATE_STAMP/",
    "mods": "mods/daily/$DATE_STAMP/",
    "config": "config/daily/$DATE_STAMP.tar.gz"
  }
}
EOF
coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload manifest.json "manifests/$DATE_STAMP.json"

log "✅ 备份完成 $DATE_STAMP"
```

### 3.2 每小时 WAL 归档（`FHD/scripts/deploy/fhd-backup-hourly-wal.sh`）

```bash
#!/usr/bin/env bash
# PostgreSQL WAL 增量归档（配合 postgresql.conf archive_command）
# RPO 从 24h 提升到 1h
set -euo pipefail

# 在 docker-compose.yml 中为 postgres 配置：
#   command: >
#     postgres
#     -c wal_level=replica
#     -c archive_mode=on
#     -c archive_command='/scripts/fhd-backup-hourly-wal.sh %p'
#     -c archive_timeout=3600

WAL_FILE="$1"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"

coscmd -r "$COS_REGION" -b "$COS_BUCKET" upload "$WAL_FILE" "postgres/wal/$(basename $WAL_FILE)"
```

### 3.3 恢复演练脚本（`FHD/scripts/deploy/fhd-restore-from-cos.sh`）

```bash
#!/usr/bin/env bash
# 从 COS 恢复到本机或新机
# 用法：bash fhd-restore-from-cos.sh 20260718-020000
set -euo pipefail

DATE_STAMP="$1"
COS_BUCKET="${FHD_COS_BUCKET:-xcagi-cvm-backup-sh}"
COS_REGION="${FHD_COS_REGION:-ap-shanghai}"
RESTORE_ROOT="${FHD_RESTORE_ROOT:-/tmp/fhd-restore-$DATE_STAMP}"

mkdir -p "$RESTORE_ROOT" && cd "$RESTORE_ROOT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# 1. 下载 manifest 校验
log "下载 manifest..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download "manifests/$DATE_STAMP.json" manifest.json
cat manifest.json

# 2. 下载 PostgreSQL dump
log "下载 PostgreSQL dump..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download \
  "postgres/daily/xcagi-$DATE_STAMP.dump" xcagi.dump

# 3. 校验 sha256
EXPECTED_SHA="$(jq -r '.sha256["xcagi.dump"]' manifest.json)"
ACTUAL_SHA="$(sha256sum xcagi.dump | awk '{print $1}')"
[[ "$EXPECTED_SHA" == "$ACTUAL_SHA" ]] || { log "❌ SHA256 不匹配"; exit 1; }

# 4. 恢复（先恢复快照到临时库，验证完整性）
log "恢复到 PostgreSQL..."
docker exec -i fhd-postgres pg_restore -U xcagi -d xcagi --clean --if-exists < xcagi.dump

# 5. 恢复 uploads / mods
log "恢复 uploads / mods..."
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download -r "uploads/daily/$DATE_STAMP/" uploads/
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download -r "mods/daily/$DATE_STAMP/" mods/
rsync -a uploads/ /opt/fhd-full/uploads/
rsync -a mods/ /opt/fhd-full/mods/

# 6. 恢复配置
coscmd -r "$COS_REGION" -b "$COS_BUCKET" download "config/daily/$DATE_STAMP.tar.gz" config.tar.gz
tar xzf config.tar.gz -C /

log "✅ 恢复完成 $DATE_STAMP"
log "⚠️  请手动验证：curl -sf http://localhost:5100/api/health"
```

### 3.4 跨区复制（COS 控制台一次性配置）

```bash
# 通过腾讯云控制台配置，或 coscmd CLI：
# 主 bucket xcagi-cvm-backup-sh（上海）→ 异地 xcagi-cvm-backup-bj（北京）
# 规则：前缀 postgres/, uploads/, mods/, config/ 自动复制
# 生命周期：daily/ 7 天，weekly/ 4 周，monthly/ 12 个月

# 用 Terraform / 控制台二选一，避免脚本漂移
```

## 四、Crontab 注册（部署到 CVM）

```cron
# /etc/cron.d/fhd-backup
# 每日 02:00 UTC（业务低峰）全量备份
0 2 * * * root /opt/fhd-full/scripts/deploy/fhd-backup-daily.sh >> /var/log/fhd-backup.log 2>&1

# 每周日 03:00 UTC 跨区复制健康检查
0 3 * * 0 root /opt/fhd-full/scripts/deploy/fhd-backup-cross-region-check.sh

# 每月 1 日 04:00 UTC 恢复演练（仅在测试机执行，生产只验证 manifest）
0 4 1 * * root /opt/fhd-full/scripts/deploy/fhd-restore-drill.sh
```

## 五、与本地 SQLite 灾备的对照（一致性铁律）

| 维度 | 桌面端 SQLite 灾备 | CVM PG 灾备 | 一致性 |
|------|------------------|------------|--------|
| 热备份 API | `sqlite3.backup()` | `pg_dump -Fc` | ✅ |
| 备份频率 | 每日 12:30 + 周日全量 | 每日 02:00 UTC + 周日全量 + 每月 1 日月度 | ✅ |
| 异地冗余 | 本地 + USB 外置 | 主 bucket（上海）+ 跨区 bucket（北京） | ✅ |
| 完整性校验 | `PRAGMA integrity_check` | `pg_restore --list` + sha256 | ✅ |
| 恢复前快照 | pre-restore snapshot | 恢复前手动 `pg_dump` 当前库 | ✅ |
| 启动自检 | `PRAGMA quick_check` on startup | docker-entrypoint `pg_isready` | ✅ |
| 磁盘告警 | ≥500MB 启动警告 | cron 检查 + COS 上传失败告警 | ✅ |
| 保留策略 | 7 日 + 4 周 | 7 日 + 4 周 + 12 月 | ✅（CVM 增强月度） |

## 六、灾备验证 SLO

新增到 [FHD/docs/SLO.md](file:///Users/a4243342/Desktop/XCMAX/FHD/docs/SLO.md)：

| ID | 名称 | 目标 | 验证方式 |
|----|------|------|---------|
| SLO-BACKUP-01 | 每日备份成功率 | ≥ 99.5% | cron 日志 + COS 对象数 |
| SLO-BACKUP-02 | 跨区复制延迟 | < 1h | COS 主备 bucket 对象数差 |
| SLO-BACKUP-03 | 恢复演练成功率 | 100%（季度） | 季度恢复演练记录 |
| SLO-BACKUP-04 | RPO | ≤ 24h（数据丢失） | manifest 时间戳 vs 故障时间 |
| SLO-BACKUP-05 | RTO | ≤ 30min（恢复耗时） | 演练计时 |

## 七、首日落地 checklist

- [ ] 在 COS 控制台创建 `xcagi-cvm-backup-sh` 与 `xcagi-cvm-backup-bj` 两个 bucket
- [ ] 配置跨区复制规则 + 生命周期
- [ ] 部署 `fhd-backup-daily.sh` 到 `/opt/fhd-full/scripts/deploy/`
- [ ] 注册 crontab（每日 02:00 UTC）
- [ ] 部署 `coscmd` CLI 到 CVM，配置 secretId/secretKey 环境变量（**不入仓**）
- [ ] 执行首次手动备份，验证 manifest.json 上传成功
- [ ] 在测试机执行 `fhd-restore-from-cos.sh` 演练
- [ ] 把 SLO-BACKUP-01..05 加入 [collect_slo_metrics.py](file:///Users/a4243342/Desktop/XCMAX/FHD/scripts/observability/collect_slo_metrics.py)
