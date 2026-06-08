# 数据库迁移方案（SQLite → PostgreSQL）

## 1. 迁移概述

本方案用于将MODstore系统的SQLite数据库迁移到PostgreSQL数据库，以提升系统的并发处理能力和可靠性。

## 2. 迁移准备

### 2.1 环境准备

| 组件 | 版本 | 说明 |
|------|------|------|
| PostgreSQL | 15.0+ | 目标数据库 |
| Python | 3.10+ | 用于执行迁移脚本 |
| psycopg2 | 2.9.9+ | PostgreSQL Python驱动 |
| sqlite3 | 内置 | SQLite Python驱动 |
| pandas | 2.0+ | 数据处理 |

### 2.2 工具安装

```bash
pip install psycopg2-binary pandas
```

### 2.3 目标数据库准备

1. **创建PostgreSQL数据库**：
   ```sql
   CREATE DATABASE payment_db;
   CREATE USER admin WITH PASSWORD 'password';
   GRANT ALL PRIVILEGES ON DATABASE payment_db TO admin;
   ```

2. **创建数据库表结构**：
   - 执行Java项目中的数据库初始化脚本
   - 或使用以下SQL语句

## 3. 数据模型映射

### 3.1 表结构映射

| SQLite表 | PostgreSQL表 | 说明 |
|---------|-------------|------|
| `users` | `users` | 用户表 |
| `wallets` | `wallets` | 钱包表 |
| `transactions` | `transactions` | 交易表 |
| `catalog_items` | 保持不变 | 商品表 |
| `purchases` | `purchase` | 购买记录表 |
| `user_mods` | 保持不变 | 用户MOD关联表 |
| `verification_codes` | 保持不变 | 验证码表 |

### 3.2 字段类型映射

| SQLite类型 | PostgreSQL类型 | 说明 |
|-----------|----------------|------|
| `INTEGER` | `SERIAL` | 自增主键 |
| `TEXT` | `TEXT` | 文本类型 |
| `VARCHAR(n)` | `VARCHAR(n)` | 字符串类型 |
| `REAL` | `DECIMAL(10,2)` | 金额类型 |
| `BOOLEAN` | `BOOLEAN` | 布尔类型 |
| `TIMESTAMP` | `TIMESTAMP` | 时间戳类型 |

## 4. 迁移步骤

### 4.1 导出SQLite数据

**创建导出脚本**：`export_sqlite.py`

```python
import sqlite3
import json
import pandas as pd
from datetime import datetime

# 连接SQLite数据库
db_path = 'modstore.db'
conn = sqlite3.connect(db_path)

# 导出用户表
def export_users():
    query = "SELECT * FROM users"
    df = pd.read_sql_query(query, conn)
    df.to_csv('users.csv', index=False)
    print("导出用户表完成")

# 导出钱包表
def export_wallets():
    query = "SELECT * FROM wallets"
    df = pd.read_sql_query(query, conn)
    df.to_csv('wallets.csv', index=False)
    print("导出钱包表完成")

# 导出交易表
def export_transactions():
    query = "SELECT * FROM transactions"
    df = pd.read_sql_query(query, conn)
    df.to_csv('transactions.csv', index=False)
    print("导出交易表完成")

# 导出商品表
def export_catalog_items():
    query = "SELECT * FROM catalog_items"
    df = pd.read_sql_query(query, conn)
    df.to_csv('catalog_items.csv', index=False)
    print("导出商品表完成")

# 导出购买表
def export_purchases():
    query = "SELECT * FROM purchases"
    df = pd.read_sql_query(query, conn)
    df.to_csv('purchases.csv', index=False)
    print("导出购买表完成")

# 导出用户MOD关联表
def export_user_mods():
    query = "SELECT * FROM user_mods"
    df = pd.read_sql_query(query, conn)
    df.to_csv('user_mods.csv', index=False)
    print("导出用户MOD关联表完成")

# 导出验证码表
def export_verification_codes():
    query = "SELECT * FROM verification_codes"
    df = pd.read_sql_query(query, conn)
    df.to_csv('verification_codes.csv', index=False)
    print("导出验证码表完成")

if __name__ == "__main__":
    export_users()
    export_wallets()
    export_transactions()
    export_catalog_items()
    export_purchases()
    export_user_mods()
    export_verification_codes()
    conn.close()
    print("所有数据导出完成")
```

### 4.2 转换数据格式

**创建转换脚本**：`transform_data.py`

```python
import pandas as pd
from datetime import datetime

# 转换用户表
def transform_users():
    df = pd.read_csv('users.csv')
    # 处理时间戳
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('users_transformed.csv', index=False)
    print("转换用户表完成")

# 转换钱包表
def transform_wallets():
    df = pd.read_csv('wallets.csv')
    # 处理时间戳
    if 'updated_at' in df.columns:
        df['updated_at'] = pd.to_datetime(df['updated_at'])
    df.to_csv('wallets_transformed.csv', index=False)
    print("转换钱包表完成")

# 转换交易表
def transform_transactions():
    df = pd.read_csv('transactions.csv')
    # 处理时间戳
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('transactions_transformed.csv', index=False)
    print("转换交易表完成")

# 转换商品表
def transform_catalog_items():
    df = pd.read_csv('catalog_items.csv')
    # 处理时间戳
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('catalog_items_transformed.csv', index=False)
    print("转换商品表完成")

# 转换购买表
def transform_purchases():
    df = pd.read_csv('purchases.csv')
    # 处理时间戳
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('purchases_transformed.csv', index=False)
    print("转换购买表完成")

# 转换用户MOD关联表
def transform_user_mods():
    df = pd.read_csv('user_mods.csv')
    # 处理时间戳
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('user_mods_transformed.csv', index=False)
    print("转换用户MOD关联表完成")

# 转换验证码表
def transform_verification_codes():
    df = pd.read_csv('verification_codes.csv')
    # 处理时间戳
    if 'expires_at' in df.columns:
        df['expires_at'] = pd.to_datetime(df['expires_at'])
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    df.to_csv('verification_codes_transformed.csv', index=False)
    print("转换验证码表完成")

if __name__ == "__main__":
    transform_users()
    transform_wallets()
    transform_transactions()
    transform_catalog_items()
    transform_purchases()
    transform_user_mods()
    transform_verification_codes()
    print("所有数据转换完成")
```

### 4.3 导入PostgreSQL

**创建导入脚本**：`import_postgres.py`

```python
import psycopg2
import pandas as pd
from sqlalchemy import create_engine

# 数据库连接信息
db_url = 'postgresql://admin:password@localhost:5432/payment_db'
engine = create_engine(db_url)

# 导入用户表
def import_users():
    df = pd.read_csv('users_transformed.csv')
    df.to_sql('users', engine, if_exists='append', index=False)
    print("导入用户表完成")

# 导入钱包表
def import_wallets():
    df = pd.read_csv('wallets_transformed.csv')
    df.to_sql('wallets', engine, if_exists='append', index=False)
    print("导入钱包表完成")

# 导入交易表
def import_transactions():
    df = pd.read_csv('transactions_transformed.csv')
    df.to_sql('transactions', engine, if_exists='append', index=False)
    print("导入交易表完成")

# 导入商品表
def import_catalog_items():
    df = pd.read_csv('catalog_items_transformed.csv')
    df.to_sql('catalog_items', engine, if_exists='append', index=False)
    print("导入商品表完成")

# 导入购买表
def import_purchases():
    df = pd.read_csv('purchases_transformed.csv')
    df.to_sql('purchase', engine, if_exists='append', index=False)
    print("导入购买表完成")

# 导入用户MOD关联表
def import_user_mods():
    df = pd.read_csv('user_mods_transformed.csv')
    df.to_sql('user_mods', engine, if_exists='append', index=False)
    print("导入用户MOD关联表完成")

# 导入验证码表
def import_verification_codes():
    df = pd.read_csv('verification_codes_transformed.csv')
    df.to_sql('verification_codes', engine, if_exists='append', index=False)
    print("导入验证码表完成")

if __name__ == "__main__":
    import_users()
    import_wallets()
    import_transactions()
    import_catalog_items()
    import_purchases()
    import_user_mods()
    import_verification_codes()
    print("所有数据导入完成")
```

### 4.4 验证数据完整性

**创建验证脚本**：`verify_data.py`

```python
import sqlite3
import psycopg2
import pandas as pd

# 连接SQLite
sqlite_conn = sqlite3.connect('modstore.db')

# 连接PostgreSQL
pg_conn = psycopg2.connect(
    host="localhost",
    database="payment_db",
    user="admin",
    password="password"
)

# 验证用户表
def verify_users():
    # SQLite数据
    sqlite_df = pd.read_sql_query("SELECT * FROM users", sqlite_conn)
    # PostgreSQL数据
    pg_df = pd.read_sql_query("SELECT * FROM users", pg_conn)
    
    print(f"用户表 - SQLite: {len(sqlite_df)} 条, PostgreSQL: {len(pg_df)} 条")
    print(f"数据一致: {len(sqlite_df) == len(pg_df)}")

# 验证钱包表
def verify_wallets():
    sqlite_df = pd.read_sql_query("SELECT * FROM wallets", sqlite_conn)
    pg_df = pd.read_sql_query("SELECT * FROM wallets", pg_conn)
    
    print(f"钱包表 - SQLite: {len(sqlite_df)} 条, PostgreSQL: {len(pg_df)} 条")
    print(f"数据一致: {len(sqlite_df) == len(pg_df)}")

# 验证交易表
def verify_transactions():
    sqlite_df = pd.read_sql_query("SELECT * FROM transactions", sqlite_conn)
    pg_df = pd.read_sql_query("SELECT * FROM transactions", pg_conn)
    
    print(f"交易表 - SQLite: {len(sqlite_df)} 条, PostgreSQL: {len(pg_df)} 条")
    print(f"数据一致: {len(sqlite_df) == len(pg_df)}")

# 验证商品表
def verify_catalog_items():
    sqlite_df = pd.read_sql_query("SELECT * FROM catalog_items", sqlite_conn)
    pg_df = pd.read_sql_query("SELECT * FROM catalog_items", pg_conn)
    
    print(f"商品表 - SQLite: {len(sqlite_df)} 条, PostgreSQL: {len(pg_df)} 条")
    print(f"数据一致: {len(sqlite_df) == len(pg_df)}")

# 验证购买表
def verify_purchases():
    sqlite_df = pd.read_sql_query("SELECT * FROM purchases", sqlite_conn)
    pg_df = pd.read_sql_query("SELECT * FROM purchase", pg_conn)
    
    print(f"购买表 - SQLite: {len(sqlite_df)} 条, PostgreSQL: {len(pg_df)} 条")
    print(f"数据一致: {len(sqlite_df) == len(pg_df)}")

if __name__ == "__main__":
    print("开始验证数据完整性...")
    verify_users()
    verify_wallets()
    verify_transactions()
    verify_catalog_items()
    verify_purchases()
    print("验证完成")
    
    sqlite_conn.close()
    pg_conn.close()
```

## 5. 迁移执行计划

### 5.1 预迁移准备

1. **备份SQLite数据库**：
   ```bash
   cp modstore.db modstore.db.backup
   ```

2. **创建PostgreSQL数据库**：
   - 执行数据库创建脚本
   - 执行表结构初始化

3. **测试连接**：
   - 验证PostgreSQL连接正常
   - 验证权限设置正确

### 5.2 执行迁移

1. **导出数据**：
   ```bash
   python export_sqlite.py
   ```

2. **转换数据**：
   ```bash
   python transform_data.py
   ```

3. **导入数据**：
   ```bash
   python import_postgres.py
   ```

4. **验证数据**：
   ```bash
   python verify_data.py
   ```

### 5.3 后迁移检查

1. **功能测试**：
   - 测试用户登录
   - 测试支付流程
   - 测试钱包功能

2. **性能测试**：
   - 测试并发处理能力
   - 测试响应时间

3. **监控**：
   - 监控数据库连接
   - 监控系统性能

## 6. 回滚方案

### 6.1 准备工作

1. **保留原SQLite数据库**：
   - 确保备份文件完整
   - 保留原系统配置

2. **配置切换机制**：
   - 准备配置文件切换脚本
   - 测试切换流程

### 6.2 回滚步骤

1. **停止新系统**：
   - 停止Java支付服务
   - 停止PostgreSQL连接

2. **恢复原系统**：
   - 恢复SQLite数据库
   - 启动原Python服务

3. **验证回滚**：
   - 测试系统功能
   - 确认数据完整性

## 7. 性能优化建议

### 7.1 PostgreSQL优化

1. **配置优化**：
   - `shared_buffers`：建议设置为总内存的25%
   - `work_mem`：根据并发连接数调整
   - `maintenance_work_mem`：设置为1GB

2. **索引优化**：
   - 为频繁查询的字段创建索引
   - 定期重建索引

3. **连接池优化**：
   - 使用HikariCP连接池
   - 合理配置连接池大小

### 7.2 应用优化

1. **缓存策略**：
   - 使用Redis缓存热点数据
   - 合理设置缓存过期时间

2. **查询优化**：
   - 使用预编译语句
   - 避免全表扫描
   - 合理使用JOIN

3. **事务管理**：
   - 缩短事务时间
   - 避免长事务

## 8. 迁移风险评估

| 风险 | 影响程度 | 可能性 | 缓解措施 |
|------|----------|--------|----------|
| 数据丢失 | 高 | 低 | 备份原数据库，验证数据完整性 |
| 服务中断 | 高 | 中 | 选择低峰期迁移，准备回滚方案 |
| 性能问题 | 中 | 中 | 优化PostgreSQL配置，监控性能 |
| 兼容性问题 | 中 | 低 | 充分测试数据类型转换 |

## 9. 结论

本迁移方案通过详细的步骤设计和风险控制，确保了从SQLite到PostgreSQL的平滑迁移。通过使用PostgreSQL的高级特性，可以显著提升MODstore系统的并发处理能力和可靠性，为用户提供更好的支付体验。

迁移完成后，系统将具备以下优势：
- **更高的并发处理能力**：PostgreSQL的多版本并发控制
- **更好的数据完整性**：完整的事务支持
- **更强的扩展性**：支持水平扩展
- **更丰富的功能**：支持JSON类型、全文搜索等高级特性

通过本方案的实施，可以为MODstore系统的长期发展奠定坚实的数据库基础。