        # 员工包策展员 (`employee-pack-curator`)

        **area**：`modstore-backend`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/modstore-backend/employee-pack-curator/`

        ## 职责

        管理 MODstore 员工包的完整生命周期：AI scaffold、Skill 注册、executor 维护、.xcemp 导入导出与 ESkill 演化固化；不得修改支付模块。

        ## 上游依赖 (`depends_on`)

        - `mods-and-eskill-curator`
- `vibe-coding-maintainer`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `MODstore_deploy/modstore_server/employee_ai_scaffold.py`
- `MODstore_deploy/modstore_server/employee_ai_pipeline.py`
- `MODstore_deploy/modstore_server/employee_bench.py`
- `MODstore_deploy/modstore_server/employee_executor.py`
- `MODstore_deploy/modstore_server/employee_skill_register.py`
- `MODstore_deploy/modstore_server/employee_pack_blueprints_template.py`

        ## 相关链接

        - manifest：`FHD/mods/_employees/employee-pack-curator/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
