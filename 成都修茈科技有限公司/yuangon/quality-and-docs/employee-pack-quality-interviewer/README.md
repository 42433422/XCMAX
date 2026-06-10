# 员工包质询员（`employee-pack-quality-interviewer`）

## 之前「面试」一个 .xcemp 时怎么做（可复用为人类/Agent 检查单）

1. **拆包**：确认 ZIP 根目录、`manifest.json`、`backend/blueprints.py`、`backend/employees/<stem>.py` 是否齐全。
2. **单一事实来源**：以 `employee_config_v2.cognition.agent.system_prompt` 为运行时准绳；若存在另一套更长提示仅躺在顶层键而 v2 很短，判为 **配置分裂（须合并）**。
3. **契约**：`actions.handlers` 必须显式；`llm_md` 需要可注入的 `call_llm`；禁止在声明 `echo` 却期望模型作答。
4. **协作图**：读取 `depends_on` 与 `employee_config_v2.collaboration.depends_on`（与 Admin 依赖画布一致）；缺失或循环依赖标出。
5. **运行依赖**：核对源仓库岗位 `README.md` 是否声明外部 API、知识库或其它 AI 岗位依赖及失效行为（可与 `employee_config_v2.metadata.runtime_dependencies` 对照）；详见 `skills/skill-xcemp-interview-rubric.md` 必查项。
6. **脚手架污染**：`script_workflows[].description` 是否夹带生成过程内心独白；若有，**上架前删改**。
7. **模型参数**：运维/安全类岗位默认倾向 `temperature` ≤ 0.4；与职责冲突则记为风险。
8. **输出**：固定模块（结论 / 阻塞项 / 建议补丁 / 复试题目），禁止编造输入中未出现的版本号或密钥。

## 在本平台怎么用

1. 在仓库内改 `prompts/system.md`、`skills/` 后，用 `MODstore_deploy` 下  
   `python -m modstore_server.scripts.onboard_yuangon_employees --pkg-ids employee-pack-quality-interviewer`  
   生成并登记包（或导出 `.xcemp` 后在「同步测试」里上传）。
2. 工作台 **发布 → 同步测试**：与 `/api/workbench/employee-bench-test` 同源流水线；服务端在通过五维静态审核后，若设置环境变量 `MODSTORE_PACK_PEER_REVIEW_EMPLOYEE=employee-pack-quality-interviewer`，会再对被测 manifest 调用本员工并解析 `MACHINE_SCORE=` 写入 `bench.audit.pack_peer_review`。若 `MODSTORE_BENCH_PEER_REVIEW_GATE=1`，质询未达标则整次基准不通过。
3. **员工工作流管理**：安装后节点会出现在「质量与文档」区，依赖边指向 **员工信息访谈员** 与 **员工包策展员**，表示应先有元数据访谈与包结构治理再质询上架质量。
