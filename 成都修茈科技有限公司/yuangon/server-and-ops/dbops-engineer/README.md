        # 数据库运维工程师 (`dbops-engineer`)

        **area**：`server-and-ops`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/server-and-ops/dbops-engineer/`

        ## 职责

        负责 ORM 模型与 Alembic 迁移、慢查询/索引/复制状态诊断、备份恢复策略与权限审计；唯一拥有 models.py / alembic / migrations 写权限的员工，所有 schema 变更必须由本岗发起或评审。

        ## 上游依赖 (`depends_on`)

        - `test-qa-runner`
- `security-secrets-guard`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试
- `agent`：启动多步 agent 执行链

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/models.py`
- `MODstore_deploy/modstore_server/migrations/**`
- `MODstore_deploy/alembic/**`
- `MODstore_deploy/alembic.ini`
- `MODstore_deploy/modstore_server/db.py`
- `MODstore_deploy/modstore_server/database*.py`

        ## 相关链接

        - manifest：`FHD/mods/_employees/dbops-engineer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
