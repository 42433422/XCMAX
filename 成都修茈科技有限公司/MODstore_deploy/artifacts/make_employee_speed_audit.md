# 做员工（make employee）速度与 LLM 投入审计

**原则：多烧 = 少返工、短路径** — Token 必须换来更短的墙钟时间、更少的 validate/六维重试、更少的规划对话轮次；不为训练指标或阻塞式「抛光」而烧。

## 北星指标

| 指标 | 说明 |
|------|------|
| 墙钟时间 | `/market/workbench/home` 从点击「开始生成」到 `complete` |
| 一次通过率 | validate + six_dim_gate 无需人工改 brief 重跑 |
| 规划轮次 | 语音/聊天里为澄清需求来回次数 |

## 路径对照

### 快路径：`word_full_extract`（模板，约 10–14s @8765）

| 步骤 | 行为 | LLM |
|------|------|-----|
| spec | 规则化 `word_extract_structured_spec`，模糊 brief 才一次结构化 LLM | 0–1 |
| employee_plan | `word_extract_orchestration_plan` 或 brief 含 pack_id+runtime_kind 时跳过规划 LLM | 0 |
| generate | 内置 convert 模板 + `_fallback_manifest`；**并行**轻量 enrich（description/behavior_rules） | 0 convert + 1 短 enrich |
| validate / six_dim | 本地校验 + 门禁 | 0 |
| pack_only | workflow/script 多数 skipped | — |

**勿用**：`force_llm_convert`、全量 `design_asset_employee_manifest` LLM、成功后再阻塞 polish。

### 富路径：`llm_scaffold` / 合同审核

| 步骤 | 行为 |
|------|------|
| spec | 模糊 brief → 一次结构化 JSON（替代多轮规划聊天） |
| employee_plan | 一站式规划 LLM（仅非确定性管线） |
| generate | 全量 manifest + vibecoding convert |
| 失败时 | `repair_runtime_convert_module` **仅** validate 报错后 1 轮 |

## 已移除（反模式）

- `MODSTORE_EMPLOYEE_HIGH_LLM_UTIL` / `MODSTORE_EMPLOYEE_FORCE_LLM_SCAFFOLD` 及 metadata 开关
- `employee_llm_util` 模块
- Word 读取默认走 LLM 写 convert（比模板慢且易 six_dim 失败）

## 代码锚点

- 路由：`modstore_server/employee_pipeline_routing.py`
- 并行生成：`employee_asset_pipeline.run_asset_employee_scaffold_async`（`asyncio.gather` convert + enrich）
- 编排：`workbench_api` employee intent + `craft_steps._craft_spec`
- 前端默认：`pack_only`；轮询 running 时 1000ms / 空闲 1500ms

## 预期耗时（pack_only + Word 全量提取 brief）

| 阶段 | 优化前（典型） | 优化后（目标） |
|------|----------------|----------------|
| spec | +1.5s LLM 常开 | 0s（确定性 brief） |
| employee_plan | +2–4s LLM | 0s（模板 plan） |
| generate manifest | +3–6s 全量 LLM | +0.8s 并行 enrich |
| generate convert | 内置 ~0s | 内置 ~0s |
| 轮询 UI | 1500ms 固定 | 1000ms running |
| **合计** | ~18–25s | **~10–14s** |

## 验证

1. 启动 API：`8765`，brief 含「全量提取」「document_full.json」「docx」「direct_python」
2. 工作台：意图「做员工」→ 目标「仅员工包」→ 开始生成
3. 步骤应显示 `word_full_extract`、generate 为「内置 convert 模板」
4. 勿覆盖 `library/word-full-read-employee`
5. 可选：`python scripts/run_word_read_employee_lab.py` 对比 `elapsed_sec`

## 下一轮（未做）

- validate 与 register_pack 更深并行（需保证 catalog 一致性）
- six_dim 失败 targeted repair（与 convert repair 统一）
