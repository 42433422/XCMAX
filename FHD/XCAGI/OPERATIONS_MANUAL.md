# XCAGI 系统运维手册

**版本**: v6.0.0  
**更新日期**: 2026-04-12  
**适用环境**: 生产环境/测试环境

---

## 📋 目录

1. [系统架构](#系统架构)
2. [部署指南](#部署指南)
3. [监控告警](#监控告警)
4. [故障排查](#故障排查)
5. [性能优化](#性能优化)
6. [备份恢复](#备份恢复)
7. [安全加固](#安全加固)
8. [常见问题](#常见问题)

---

## 系统架构

### 技术栈

```
前端：Vue 3 + TypeScript + Element Plus
后端：FastAPI + Flask (过渡期) + Neuro-DDD
数据库：PostgreSQL + pgvector
缓存：Redis
消息队列：Redis (Celery Broker)
任务队列：Celery
部署：Docker + Docker Compose
```

### 架构图

```
┌─────────────┐
│   Nginx     │ 反向代理
└──────┬──────┘
       │
   ┌───┴───┐
   │       │
┌──┴──┐ ┌─┴──────┐
│FastAPI│ │Flask  │ (逐步迁移)
└──┬──┘ └─┬──────┘
   │       │
   └───┬───┘
       │
   ┌───┴────┐
   │Neuro-DDD│ 业务总线
   └───┬────┘
       │
   ┌───┴────┐
   │PostgreSQL│
   │  Redis   │
   └──────────┘
```

---

## 部署指南

### 环境要求

- **操作系统**: Linux (Ubuntu 20.04+) / Windows Server 2019+
- **CPU**: 4 核 +
- **内存**: 8GB +
- **磁盘**: 100GB +
- **Python**: 3.11+

### Docker 部署

#### 1. 启动服务

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

#### 2. 服务列表

```yaml
services:
  - web: FastAPI + Flask Web 服务
  - postgres: PostgreSQL 数据库
  - redis: Redis 缓存
  - celery-worker: Celery 工作节点
  - celery-beat: Celery 定时任务
```

#### 3. 健康检查

```bash
# 检查 Web 服务
curl http://localhost:8000/api/health

# 检查数据库
docker-compose exec postgres pg_isready

# 检查 Redis
docker-compose exec redis redis-cli ping
```

### 手动部署

#### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

#### 2. 配置环境变量

```bash
# .env 文件
DATABASE_URL=postgresql://user:pass@localhost:5432/xcagi
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
ENV=production
```

#### 3. 初始化数据库

```bash
# 运行数据库迁移
python -m app.db.migrate

# 加载初始数据
python scripts/seed_data.py
```

#### 4. 启动服务

```bash
# 启动 FastAPI (生产环境使用 uvicorn/gunicorn)
uvicorn app.fastapi_app:app --host 0.0.0.0 --port 8000 --workers 4

# 启动 Celery Worker
celery -A app.celery_app worker --loglevel=info --concurrency=4

# 启动 Celery Beat
celery -A app.celery_app beat --loglevel=info
```

---

## 监控告警

### 系统监控

#### 1. 应用指标

```python
# Prometheus 指标端点
GET /metrics

# 关键指标:
- http_requests_total: 请求总数
- http_request_duration_seconds: 请求耗时
- active_requests: 活跃请求数
- celery_tasks_total: 任务总数
- celery_tasks_runtime: 任务执行时间
```

#### 2. 数据库监控

```sql
-- 连接数
SELECT count(*) FROM pg_stat_activity;

-- 慢查询
SELECT query, calls, total_time, rows
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;

-- 表大小
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

#### 3. Redis 监控

```bash
# 内存使用
redis-cli INFO memory

# 连接信息
redis-cli INFO clients

# 命中率
redis-cli INFO stats | grep keyspace
```

### 日志监控

#### 1. 日志级别

```python
DEBUG: 调试信息
INFO:  正常信息
WARNING: 警告信息
ERROR: 错误信息
CRITICAL: 严重错误
```

#### 2. 日志位置

```bash
# 应用日志
/var/log/xcagi/app.log

# Nginx 日志
/var/log/nginx/access.log
/var/log/nginx/error.log

# Docker 日志
docker-compose logs web
docker-compose logs celery-worker
```

#### 3. 日志分析

```bash
# 错误日志
grep "ERROR" /var/log/xcagi/app.log | tail -100

# 慢请求
grep "slow" /var/log/xcagi/app.log

# 统计错误数
grep -c "ERROR" /var/log/xcagi/app.log
```

### 告警规则

#### 1. 应用告警

| 指标 | 阈值 | 告警级别 |
|------|------|---------|
| 错误率 | > 1% | 严重 |
| 响应时间 P95 | > 2s | 警告 |
| 5xx 错误数 | > 10/分钟 | 严重 |
| 4xx 错误数 | > 100/分钟 | 警告 |

#### 2. 系统告警

| 指标 | 阈值 | 告警级别 |
|------|------|---------|
| CPU 使用率 | > 80% | 警告 |
| 内存使用率 | > 85% | 警告 |
| 磁盘使用率 | > 90% | 严重 |
| 数据库连接数 | > 80% | 警告 |

#### 3. 告警通知

```yaml
# 通知渠道
- 邮件：ops@company.com
- 企业微信：运维告警群
- 短信：值班人员

# 告警升级
- 5 分钟未响应 → 通知主管
- 15 分钟未响应 → 通知总监
```

---

## 故障排查

### 诊断流程

```
1. 收集信息
   - 错误现象
   - 影响范围
   - 发生时间
   - 错误日志

2. 定位问题
   - 查看应用日志
   - 检查系统指标
   - 分析数据库慢查询
   - 检查外部服务

3. 解决问题
   - 临时方案（恢复服务）
   - 根本解决（修复 bug）
   - 预防措施（避免复发）

4. 总结复盘
   - 问题原因
   - 处理过程
   - 改进措施
```

### 常见问题

#### 1. 应用无法启动

**症状**:
- 服务无法访问
- 端口未监听

**排查步骤**:

```bash
# 1. 检查进程
ps aux | grep python
docker-compose ps

# 2. 检查端口
netstat -tlnp | grep 8000

# 3. 查看日志
docker-compose logs web
tail -f /var/log/xcagi/app.log

# 4. 检查配置
python -c "from app.config import Config; print(Config.DATABASE_URL)"

# 5. 检查依赖
pip list | grep fastapi
```

**解决方案**:

```bash
# 重启服务
docker-compose restart web

# 重新部署
docker-compose down
docker-compose up -d

# 检查数据库连接
python -c "from app.db import engine; print(engine.connect())"
```

#### 2. 数据库连接失败

**症状**:
- 数据库连接超时
- 连接数已满

**排查步骤**:

```bash
# 1. 检查数据库状态
docker-compose exec postgres pg_isready

# 2. 查看连接数
docker-compose exec postgres psql -U xcagi -c "SELECT count(*) FROM pg_stat_activity;"

# 3. 检查慢查询
docker-compose exec postgres psql -U xcagi -c "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"

# 4. 查看数据库日志
docker-compose logs postgres
```

**解决方案**:

```bash
# 重启数据库
docker-compose restart postgres

# 清理空闲连接
docker-compose exec postgres psql -U xcagi -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle';"

# 增加最大连接数
# 修改 postgresql.conf: max_connections = 200
docker-compose restart postgres
```

#### 3. Redis 连接失败

**症状**:
- 缓存失效
- Celery 任务不执行

**排查步骤**:

```bash
# 1. 检查 Redis 状态
docker-compose exec redis redis-cli ping

# 2. 查看内存
docker-compose exec redis redis-cli INFO memory

# 3. 查看连接
docker-compose exec redis redis-cli INFO clients

# 4. 查看日志
docker-compose logs redis
```

**解决方案**:

```bash
# 重启 Redis
docker-compose restart redis

# 清理内存
docker-compose exec redis redis-cli FLUSHDB

# 检查配置
docker-compose exec redis redis-cli CONFIG GET maxmemory
```

#### 4. Celery 任务堆积

**症状**:
- 任务执行延迟
- Worker 负载高

**排查步骤**:

```bash
# 1. 查看队列长度
docker-compose exec redis redis-cli LLEN celery

# 2. 查看 Worker 状态
celery -A app.celery_app inspect active
celery -A app.celery_app inspect stats

# 3. 查看任务执行
celery -A app.celery_app inspect reserved

# 4. 查看日志
docker-compose logs celery-worker
```

**解决方案**:

```bash
# 增加 Worker 数量
docker-compose up -d --scale celery-worker=8

# 重启 Worker
docker-compose restart celery-worker

# 清理任务队列
docker-compose exec redis redis-cli DEL celery
```

#### 5. API 响应慢

**症状**:
- 请求超时
- 响应时间长

**排查步骤**:

```bash
# 1. 查看慢请求
grep "slow" /var/log/xcagi/app.log

# 2. 查看数据库慢查询
docker-compose exec postgres psql -U xcagi -c "SELECT query, total_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"

# 3. 查看系统负载
top
htop

# 4. 查看网络
iftop
```

**解决方案**:

```bash
# 优化数据库查询
# 添加索引
CREATE INDEX idx_order_number ON shipments(order_number);

# 清理历史数据
DELETE FROM logs WHERE created_at < NOW() - INTERVAL '30 days';

# 增加缓存
# 在应用层添加 Redis 缓存

# 扩容
docker-compose up -d --scale web=4
```

#### 6. 内存泄漏

**症状**:
- 内存持续增长
- 服务频繁重启

**排查步骤**:

```bash
# 1. 监控内存
watch -n 1 'ps aux | grep python'

# 2. 分析内存
pip install memory_profiler
python -m memory_profiler app/fastapi_app.py

# 3. 查看 GC
python -c "import gc; gc.set_debug(gc.DEBUG_LEAK)"
```

**解决方案**:

```bash
# 1. 限制 Worker 内存
# gunicorn --max-requests 1000 --max-requests-jitter 50

# 2. 定期重启
docker-compose restart web

# 3. 修复代码
# 检查全局变量、缓存、连接池等
```

#### 7. 磁盘空间不足

**症状**:
- 写入失败
- 服务异常

**排查步骤**:

```bash
# 1. 查看磁盘使用
df -h

# 2. 查找大文件
du -ah /var/log | sort -rh | head -20

# 3. 查看 Docker 占用
docker system df
```

**解决方案**:

```bash
# 1. 清理日志
> /var/log/xcagi/app.log

# 2. 清理 Docker
docker system prune -a

# 3. 清理数据库
VACUUM FULL;

# 4. 扩容磁盘
```

---

## 性能优化

### 数据库优化

#### 1. 索引优化

```sql
-- 添加索引
CREATE INDEX idx_shipment_order ON shipments(order_number);
CREATE INDEX idx_shipment_status ON shipments(status);
CREATE INDEX idx_shipment_created ON shipments(created_at);

-- 复合索引
CREATE INDEX idx_shipment_customer_status ON shipments(customer_id, status);

-- 查看索引使用
EXPLAIN ANALYZE SELECT * FROM shipments WHERE order_number = 'SO12345';
```

#### 2. 查询优化

```sql
-- 避免 SELECT *
SELECT id, order_number, status FROM shipments;

-- 使用 JOIN 代替子查询
SELECT s.*, c.name
FROM shipments s
JOIN customers c ON s.customer_id = c.id;

-- 分页优化
SELECT * FROM shipments ORDER BY created_at DESC LIMIT 20 OFFSET 0;
```

#### 3. 连接池优化

```python
# SQLAlchemy 配置
SQLALCHEMY_POOL_SIZE = 20
SQLALCHEMY_MAX_OVERFLOW = 40
SQLALCHEMY_POOL_TIMEOUT = 30
SQLALCHEMY_POOL_RECYCLE = 3600
```

### 缓存优化

#### 1. Redis 缓存策略

```python
from functools import lru_cache
import redis

# 应用层缓存
@lru_cache(maxsize=1024)
def get_customer(customer_id: int):
    return db.query(Customer).get(customer_id)

# Redis 缓存
r = redis.Redis()

def get_with_cache(key: str, ttl: int = 300):
    cached = r.get(key)
    if cached:
        return json.loads(cached)
    
    data = query_database()
    r.setex(key, ttl, json.dumps(data))
    return data
```

#### 2. 缓存预热

```python
# 启动时预热常用数据
def warm_up_cache():
    # 缓存配置
    cache_config()
    
    # 缓存字典数据
    cache_dictionaries()
    
    # 缓存热点数据
    cache_hot_data()
```

### 应用优化

#### 1. 异步处理

```python
# 使用异步 IO
@app.get("/api/data")
async def get_data():
    data = await fetch_data_async()
    return data

# 后台任务
@app.post("/api/export")
async def export_data():
    task_id = celery_task.delay()
    return {"task_id": task_id}
```

#### 2. 批量处理

```python
# 批量插入
db.bulk_insert_mappings(Shipment, shipments)

# 批量更新
db.bulk_update_mappings(Shipment, updates)
```

#### 3. 连接复用

```python
# 使用连接池
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_recycle=3600
)
```

---

## 备份恢复

### 数据库备份

#### 1. 自动备份

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/postgresql"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="xcagi"
DB_USER="xcagi"

# 全量备份
pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/$DB_NAME_$DATE.sql.gz

# 保留最近 7 天
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete

# 上传到云存储
aws s3 cp $BACKUP_DIR/$DB_NAME_$DATE.sql.gz s3://backup-bucket/postgresql/
```

#### 2. 手动备份

```bash
# 全量备份
pg_dump -U xcagi xcagi | gzip > backup.sql.gz

# 仅结构
pg_dump -U xcagi -s xcagi > schema.sql

# 仅数据
pg_dump -U xcagi -a xcagi > data.sql

# 单个表
pg_dump -U xcagi -t shipments xcagi > shipments.sql
```

#### 3. 恢复数据

```bash
# 从备份恢复
gunzip < backup.sql.gz | psql -U xcagi xcagi

# 从 SQL 文件恢复
psql -U xcagi xcagi < schema.sql
psql -U xcagi xcagi < data.sql
```

### 应用备份

#### 1. 代码备份

```bash
# Git 备份
git clone git@github.com:company/xcagi.git /backup/code

# 打包备份
tar -czf /backup/code_$(date +%Y%m%d).tar.gz /path/to/code
```

#### 2. 配置备份

```bash
# 备份配置文件
cp .env /backup/env_$(date +%Y%m%d)
cp docker-compose.yml /backup/docker-compose_$(date +%Y%m%d).yml
```

### 恢复流程

#### 1. 数据库恢复

```bash
# 1. 停止应用
docker-compose down

# 2. 恢复数据库
gunzip < backup.sql.gz | docker-compose exec -T postgres psql -U xcagi xcagi

# 3. 启动应用
docker-compose up -d

# 4. 验证
curl http://localhost:8000/api/health
```

#### 2. 应用恢复

```bash
# 1. 恢复代码
git checkout <version>

# 2. 恢复配置
cp /backup/env_<date> .env

# 3. 重新部署
docker-compose up -d
```

---

## 安全加固

### 1. 访问控制

```yaml
# Nginx 配置
server {
    listen 443 ssl;
    
    # SSL 证书
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    # 限制 IP
    allow 192.168.1.0/24;
    deny all;
    
    # 限流
    limit_req zone=one burst=10;
}
```

### 2. 认证授权

```python
# JWT Token
from jose import jwt

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

def create_token(data: dict):
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
```

### 3. 数据加密

```python
# 敏感数据加密
from cryptography.fernet import Fernet

key = Fernet.generate_key()
cipher = Fernet(key)

# 加密
encrypted = cipher.encrypt(b"sensitive_data")

# 解密
decrypted = cipher.decrypt(encrypted)
```

### 4. SQL 注入防护

```python
# 使用参数化查询
# ✅ 正确
db.execute("SELECT * FROM users WHERE id = :id", {"id": user_id})

# ❌ 错误
db.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

### 5. XSS 防护

```python
# 转义输出
from markupsafe import escape

html = escape(user_input)
```

---

## 常见问题

### Q1: 如何查看系统状态？

```bash
# 查看所有服务
docker-compose ps

# 查看日志
docker-compose logs -f

# 查看资源使用
docker stats
```

### Q2: 如何重启服务？

```bash
# 重启单个服务
docker-compose restart web

# 重启所有服务
docker-compose restart
```

### Q3: 如何扩容？

```bash
# 增加 Web 实例
docker-compose up -d --scale web=4

# 增加 Worker 数量
docker-compose up -d --scale celery-worker=8
```

### Q4: 如何查看数据库？

```bash
# 进入数据库
docker-compose exec postgres psql -U xcagi

# 查看表
\dt

# 查看数据
SELECT * FROM shipments LIMIT 10;
```

### Q5: 如何清理日志？

```bash
# 清空日志文件
> /var/log/xcagi/app.log

# Docker 日志清理
docker-compose logs --tail=100

# 系统日志清理
journalctl --vacuum-time=1d
```

### Q6: 如何回滚版本？

```bash
# Git 回滚
git checkout <previous_version>

# 重新部署
docker-compose down
docker-compose up -d
```

### Q7: 紧急联系人？

```
运维负责人：张三 13800138000
技术负责人：李四 13900139000
值班电话：400-xxx-xxxx
```

---

## 附录

### A. 常用命令速查

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down

# 重启
docker-compose restart

# 日志
docker-compose logs -f [service]

# 进入容器
docker-compose exec [service] bash

# 查看状态
docker-compose ps

# 扩容
docker-compose up -d --scale [service]=N

# 备份
pg_dump -U xcagi xcagi | gzip > backup.sql.gz

# 恢复
gunzip < backup.sql.gz | psql -U xcagi xcagi
```

### B. 配置文件模板

```yaml
# docker-compose.yml
version: '3'
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://xcagi:pass@postgres:5432/xcagi
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
  
  postgres:
    image: postgres:14
    environment:
      - POSTGRES_USER=xcagi
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=xcagi
    volumes:
      - postgres_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7
    volumes:
      - redis_data:/data
  
  celery-worker:
    build: .
    command: celery -A app.celery_app worker --loglevel=info
    depends_on:
      - postgres
      - redis

volumes:
  postgres_data:
  redis_data:
```

---

**文档版本**: v1.0  
**创建日期**: 2026-04-12  
**最后更新**: 2026-04-12  
**维护团队**: 运维部
