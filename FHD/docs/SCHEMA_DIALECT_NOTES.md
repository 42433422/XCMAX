# 模式方言分叉（Schema Dialect Forks）— 有意为之的设计

> 本文把 FHD 在 **SQLite（桌面 / 单机企业）** 与 **PostgreSQL（云多租户）** 之间
> *故意* 不一致的存储设计写成白纸黑字，避免未来的你 / AI 员工把它误判成 bug 或
> schema 漂移。这些分叉是按方言取最优解的结果，不是疏漏。

最后更新：2026-06-23

## 一、向量存储（最重要的一处分叉）

同一份「向量索引」能力，两套后端用**不同的列类型与检索算法**落地：

| 维度 | PostgreSQL | SQLite |
|------|-----------|--------|
| 扩展 | `CREATE EXTENSION vector`（pgvector） | 无扩展，纯标准 SQLite |
| 嵌入列 | `embedding vector(256)` | `embedding TEXT`（JSON 编码的 float 数组） |
| 检索算法 | ANN 近似最近邻，`ivfflat` 索引 + `vector_cosine_ops`，余弦距离算子 `<=>` | **暴力精确**：把候选行读进进程，用 Python 逐行算余弦相似度 |
| ANN 索引 | 有（`USING ivfflat`） | **无**（只有 `index_id` / `tenant_id` 等 B-tree 元数据索引） |

实现位置：

- PG：[app/infrastructure/persistence/pg_vector_store.py](../app/infrastructure/persistence/pg_vector_store.py)
  （`embedding vector(256)` + `CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops)`）；
  数据集 RAG 的 PG 变体见 [app/infrastructure/rag/dataset_vector_index.py](../app/infrastructure/rag/dataset_vector_index.py)
  （同样走 `ivfflat`）。
- SQLite：[app/infrastructure/rag/dataset_vector_index.py](../app/infrastructure/rag/dataset_vector_index.py)
  —— 列 `embedding TEXT NOT NULL`，类文档自述「SQLite plus **in-process cosine ranking**」，
  排序由 `_cosine()` 在 Python 内完成。

**为什么这样设计（不是 bug）**：

- SQLite 没有 pgvector，无法存原生 `vector` 列或建 ANN 索引——这是方言能力差异，不是缺陷。
- 单机 / 桌面企业的数据集规模小，**暴力精确余弦**召回率 = 100%，比 ANN 近似更准且实现零依赖；
  在该规模下暴力扫描的延迟可接受。
- 云端 PG 面向多租户大规模，才需要 `ivfflat` 这类 ANN 索引牺牲一点召回换吞吐。

所以：**桌面 SQLite 看不到 `vector(256)` / `ivfflat` 是预期的**，不要去给 SQLite「补」一个
pgvector 列或 ANN 索引——那会直接失败（无扩展），且违背设计意图。

## 二、非 ORM 表：按方言用裸 DDL 建，alembic 故意不纳管

部分表**有意不建模进 ORM**，因此 `alembic` 的 autogenerate 把它们排除在外，
`alembic check` 不会尝试 DROP 它们：

- 排除名单见 [alembic/env.py](../alembic/env.py) 的 `_NON_ORM_TABLES` 与 `_include_name()`，
  与压缩基线 [alembic/versions/2026_06_22_baseline_squashed_schema.py](../alembic/versions/2026_06_22_baseline_squashed_schema.py)
  里的 `_NON_ORM_PG_DDL` 保持同步。
- 典型成员：`excel_vector_indexes` / `excel_vector_chunks`（PG 向量表，含 `vector(256)`，
  ORM 无法表达原生 pgvector 类型，故走裸 SQL）、`templates` / `template_usage_log`
  （Excel 模板，历史上由 [app/db/init_db.py](../app/db/init_db.py) 的 `init_template_tables`
  以裸 SQLite `ALTER TABLE ... ADD COLUMN` 逐列演进）。

**为什么这样设计**：原生 pgvector 类型 ORM 表达不了；模板表是早期裸 SQL 演进的历史包袱。
两者都在 alembic 之外，但都被显式登记在排除名单里——是「明示不纳管」，不是「漏了」。

## 三、与 alembic schema 门禁的关系

[../.github/workflows/fhd-alembic-ssot.yml](../../.github/workflows/fhd-alembic-ssot.yml) 用两条平行的
parity 门禁守护「全新空库能否仅靠 alembic 建出 == ORM」：

- `ssot-parity-sqlite`：**阻断**。SQLite autogenerate 是确定性的，无类型 / server_default 假阳性。
- `ssot-parity`（PostgreSQL）：**report-only**，因为 PG autogenerate 可能就上面这些方言差异
  报出 `compare_type` / `compare_server_default` 假阳性（可在 `alembic/env.py` 调参消除）。

换言之，本文记录的方言分叉，正是 PG parity 暂时保持 report-only 的根因之一；遇到 PG
autogenerate 报出 `vector` / 默认值差异时，先对照本文判断是否「预期方言差异」，再决定调参还是改 schema。

## 四、新增列的正确姿势（避免再造第二真相源）

运行时 `ensure_*` 补列只用于把 **ORM 已声明** 的列回填进旧库，**不得**用它引入 ORM 不知道的新列
（由 [tests/test_db/test_ensure_columns_frozen.py](../tests/test_db/test_ensure_columns_frozen.py) 冻结守护）。
新增业务列请走：改 ORM 模型 → 写 alembic 迁移 → 让 `create_all` / alembic 自然带出。
