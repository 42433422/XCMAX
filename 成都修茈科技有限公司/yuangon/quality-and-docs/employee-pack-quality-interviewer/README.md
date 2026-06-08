        # 员工包质询员 (`employee-pack-quality-interviewer`)

        **area**：`quality-and-docs`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/quality-and-docs/employee-pack-quality-interviewer/`

        ## 职责

        对候选 employee_pack（.xcemp）做结构化「入职面试」：基于用户粘贴的 manifest 节选、同步测试日志或
沙盒 JSON，对照职责边界与平台契约给出录用/有条件录用/驳回结论与可执行修改清单。
不替代渗透测试、法务合规或正式 HR 录用；不编造未出现在输入中的文件路径、接口或密钥。

        ## 上游依赖 (`depends_on`)

        - `employee-interview-assistant`
- `employee-pack-curator`

        ## 支持的 Handlers

        - `llm_md`：接收 Markdown 任务描述，调用 LLM 输出结构化结果
- `echo`：调试用：原样返回输入，用于 smoke 测试

        ## Scope（核心文件范围）

        - `yuangon/**/employee.yaml`
- `yuangon/**/prompts/*.md`
- `yuangon/**/skills/*.md`
- `yuangon/quality-and-docs/employee-pack-quality-interviewer/**`

        ## 相关链接

        - manifest：`FHD/mods/_employees/employee-pack-quality-interviewer/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
