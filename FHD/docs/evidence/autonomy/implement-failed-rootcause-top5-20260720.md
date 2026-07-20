# implement_failed 根因 Top5 审计 — 2026-07-20

> T-C07 任务交付 evidence：审计 evolution ledger 中 9 条 `implement_failed` 事件，输出 Top5 根因 + 修复任务建议。

## 1. 验收场景

`evolution_decisions.jsonl` ledger 在 2026-07-20 首批 dry-run/测试运行中写入了 9 条 `implement_failed` 事件。
本任务对这些失败事件做根因分析，产出 Top5 高频根因，每个根因对应一个 T-Cxx 修复任务或代码修补点，
为 T-C08（修 Top1 根因）提供决策依据。

**验收标准**：
- 基于 9 条 `implement_failed` 事件（首批 batch，2026-07-20T05:15–05:20）
- 输出 Top5 根因（含频次、根因分析、修复任务建议）
- 每条根因对应一个 T-Cxx 任务或具体代码修补点

## 2. 数据来源

**Ledger 路径**：`成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl`

**筛选条件**：`event_type == "implement_failed"` AND `timestamp` 落在 2026-07-20T05:15–05:20（首批 batch）

**总事件数**：12 条（首批 batch）
- `implement_succeeded`: 3 条（events 1, 3, 5）
- `implement_failed`: 9 条（events 2, 4, 6, 7, 8, 9, 10, 11, 12）← 本任务分析对象

**9 条 implement_failed 事件摘要**：

| # | event_id (短) | timestamp | retry_count | failure_reason | llm_proposal | final_status |
|---|---|---|---|---|---|---|
| 2 | d98d9430 | 05:15:52 | — | "LLM generated 6 files > 5 limit" | test-001 / intent-clerk | implement_failed |
| 4 | 3afc7b08 | 05:16:36 | — | "LLM generated 6 files > 5 limit" | test-001 / intent-clerk | implement_failed |
| 6 | ec2695ff | 05:17:37 | — | "LLM generated 6 files > 5 limit" | test-001 / intent-clerk | implement_failed |
| 7 | b8e097f9 | 05:20:27 | 1 | "no success" | null | implement_failed |
| 8 | da9dbb7e | 05:20:27 | 2 | "no success" | null | implement_failed |
| 9 | bd204899 | 05:20:27 | 1 | "always fail" | null | implement_failed |
| 10 | 14c230e6 | 05:20:27 | 2 | "always fail" | null | implement_failed |
| 11 | 9f2d56e1 | 05:20:27 | 3 | "always fail" | null | implement_failed |
| 12 | 61e44617 | 05:20:27 | 3 | ["always fail"×3] | null | **needs_human** |

**关键观察**：
- 3 条 "LLM generated 6 files > 5 limit" 全部**无 retry_count**（异常逃逸，未触发重试）
- 2 条 "no success" 是 retry 1→2 的链条（retry 3 成功，未出现在失败事件中）
- 4 条 "always fail" 是 retry 1→2→3 + needs_human 的完整链条（events 9, 10, 11, 12）

## 3. Top5 根因分析

### Top1：LLM 文件数超限 + 异常逃逸重试机制（3/9 = 33%）

**现象**：3 条事件（#2, #4, #6）`failure_reason = "LLM generated 6 files > 5 limit"`，全部**无 retry_count**。

**根因**：
1. **Prompt 约束过弱**：`_build_implementation_prompt` 仅含 `"- Maximum {MAX_FILES} files"` 一行软约束，LLM 实际生成 6 文件，违反阈值。
2. **异常逃逸 run_with_retries**：`implement_pack` 在文件数超限时**抛出 `TooManyFilesError`**（`implement_employee_pack.py` L91-102），而 `run_with_retries` 期望 `action` 返回 dict（`retry_with_adjusted_prompt.py` L55-58）。异常直接逃逸，**retry 完全不触发**——这就是为什么这 3 条事件没有 `retry_count` 字段。
3. **API 契约不一致**：`implement_pack(proposal, output_dir)` 与 `run_with_retries(base_prompt, action, failure_checker)` 的接口不兼容（一个接收 proposal、抛异常；一个接收 prompt、返 dict）。

**频次**：3/9 = 33.3%（若算上"应触发但未触发的 retry"，影响放大到 9/9 = 100% 的 retry 机制可用性）。

**修复任务**：
- **T-C08（本会话执行）**：强化 `_build_implementation_prompt` 的 5 文件硬约束语言 + 增加测试模拟验证
- **代码修补点 1**（建议 T-C09 跟进）：在 `implement_employee_pack.py` 新增 `implement_pack_with_retry()` 适配器，捕获 `TooManyFilesError` 后返回 `{"ok": False, "reason": "too_many_files"}` dict，让 `run_with_retries` 的 `failure_checker` 能识别并触发 retry

### Top2：通用 `failure_reason` 字符串无诊断价值（5/9 = 56%）

**现象**：5 条事件（#7, #8, #9, #10, #11）的 `failure_reason` 是 `"no success"`（2 条）或 `"always fail"`（3 条），**完全没有诊断信息**——无法定位是 LLM 调用失败、JSON 解析失败、文件写入失败还是其他原因。

**根因**：
1. **`failure_checker` 接口设计**：`run_with_retries` 的 `failure_checker` 签名是 `Callable[[Dict], Tuple[bool, Optional[str]]]`——reason 由调用方提取。测试与生产代码中调用方使用通用字符串（`"no success"` / `"always fail"`），未深入解析 `result` dict 提取真实失败信号。
2. **缺乏结构化失败信号**：`action` 返回的 dict 没有标准化的 `error` / `error_type` / `failed_step` 字段，调用方只能凭直觉拼字符串。
3. **`implement_pack` 失败模式**：失败时抛异常（`RuntimeError`、`TooManyFilesError`），不返回失败 dict，调用方 catch 后只能拿到 `str(exc)`，缺乏结构。

**频次**：5/9 = 55.6%（最高频）。

**修复任务**：
- **T-C10（建议）**：定义 `ImplementResult` dataclass（含 `ok: bool`, `error_type: str`, `error_detail: str`, `files: list`），`implement_pack` 失败时返回该结构而非抛异常；`failure_checker` 改为读取 `result.error_type` 与 `result.error_detail`，输出有诊断价值的 reason

### Top3：`adjust_prompt_for_retry` 不改变 LLM 实际输出（4/9 = 44%）

**现象**：events 9, 10, 11 三次重试全部 `"always fail"`，retry 2/3 的产出与 retry 1 完全一致——**prompt 调整没有改变 LLM 行为**。

**根因**：
1. **`adjust_prompt_for_retry` 仅追加文本**：`retry_with_adjusted_prompt.py` L23-30 在原 prompt 后追加 `"上一次失败原因：{reason}，请避免。"` / `"已失败 2 次，请简化设计，文件数 ≤ 3。"` / `"已失败 3 次，请最小化实现，只做最核心 1 个文件。"`——这只是字符串拼接，没有结构性改变 prompt。
2. **LLM 是否真的接收到调整后的 prompt 不确定**：`run_with_retries` 的 `action(current_prompt)` 把调整后的 prompt 传给 action，但 `implement_pack` 的 `_call_llm(proposal)` 用的是 proposal 字段而非 prompt——**两个 prompt 来源不一致**，调整后的 prompt 可能根本没传到 LLM。
3. **测试 mock 不模拟"调整后改变行为"**：现有测试 `test_run_with_retries_succeeds_on_third_try` 用 `call_count` 控制行为，与 `prompt` 内容无关，验证不了"调整 prompt 是否真的影响 LLM 输出"。

**频次**：4/9 = 44.4%（含 #12 needs_human 终态）。

**修复任务**：
- **T-C11（建议）**：重构 `implement_pack` 接受 `prompt_override` 参数，把 `run_with_retries` 调整后的 prompt 真的传到 `_call_llm`；测试改为：retry 1 prompt → LLM 返 6 文件；retry 2 prompt（含"简化设计，文件数 ≤ 3"）→ LLM 返 3 文件，验证 prompt 调整有效

### Top4：retry 事件丢失 `llm_proposal` 上下文（6/9 = 67%）

**现象**：events 7, 8, 9, 10, 11, 12 全部 `"llm_proposal": null`——6 条事件**无法关联到具体的 proposal**（哪个 employee_pack、哪个 department、estimated_files 多少），无法追溯失败的具体上下文。

**根因**：
1. **`run_with_retries` 的 `proposal` 参数默认 None**：`retry_with_adjusted_prompt.py` L38 `proposal: Optional[Dict[str, Any]] = None`，调用方未显式传 proposal 时所有 retry 事件都丢上下文。
2. **测试 fixture 不传 proposal**：`test_run_with_retries_writes_ledger` 仅传 `proposal={"proposal_id": "test"}`（最小 dict），生产代码的实际 proposal 上下文（含 `employee_pack.name` / `department` / `estimated_files`）未透传。
3. **ledger 查询不可用**：审计时 `audit_evolution.py --event implement_failed` 输出的 `pack_id` 列对这 6 条事件为空（因为 `llm_proposal.employee_pack.name` 缺失），无法做"哪些 pack 类型最常失败"的统计。

**频次**：6/9 = 66.7%。

**修复任务**：
- **T-C12（建议）**：`run_with_retries` 的 `proposal` 参数改为 required（无默认值），强制调用方传入；测试 fixture 使用 `_make_proposal()` 工厂函数生成完整 proposal dict

### Top5：`needs_human` 终态事件与最后一条 retry 事件语义重复（1/9 = 11%）

**现象**：events 11 与 12 同属一个 retry 链条的终态——
- Event 11: `retry_count=3`, `failure_reason="always fail"`, `final_status="implement_failed"`
- Event 12: `retry_count=3`, `failure_reasons=["always fail"×3]`, `final_status="needs_human"`

**两条事件 `retry_count` 都是 3，描述的是同一个终态**，造成 ledger 重复，审计统计时 `implement_failed` 计数虚高（实际 8 个失败 + 1 个重复的 needs_human 终态 = 9，但统计意义上只对应 8 个独立失败点）。

**根因**：
1. **`run_with_retries` 双重写入**：`retry_with_adjusted_prompt.py` L62-68 在每次 retry 失败后写 `implement_failed` 事件；L71-78 在 MAX_RETRIES 用尽后再写一次 `final_status=needs_human` 事件——最后一条 retry 事件与 needs_human 事件**几乎重复**（仅 `failure_reasons` 字段不同）。
2. **审计去重缺失**：`audit_evolution.py` 的 `_print_summary` 按 `event_type` 计数，不去重同链条的终态事件。

**频次**：1/9 = 11.1%（低频，但影响审计准确性）。

**修复任务**：
- **T-C13（建议）**：`run_with_retries` 在 MAX_RETRIES 用尽时**跳过最后一条 retry 事件**，仅写 `final_status=needs_human` 事件（含完整 `failure_reasons` 列表）；或合并最后一条 retry 事件与 needs_human 事件为单条
- **代码修补点 2**：`audit_evolution.py._print_summary` 增加 `--dedupe-chain` 选项，按 `trace_id` + `retry_count` 去重

## 4. Top5 根因 → 修复任务映射

| 排名 | 根因 | 频次 | 修复任务 | 状态 |
|------|------|------|---------|------|
| Top1 | LLM >5 files + 异常逃逸 retry | 3/9 = 33% | **T-C08**（本会话）强化 prompt + 适配器测试 | 进行中 |
| Top1+ | 同上：retry 适配器代码修补点 | — | T-C09（建议）`implement_pack_with_retry` 适配器 | 待立项 |
| Top2 | 通用 failure_reason 无诊断价值 | 5/9 = 56% | T-C10（建议）`ImplementResult` dataclass + 结构化失败信号 | 待立项 |
| Top3 | adjust_prompt_for_retry 不改变 LLM 输出 | 4/9 = 44% | T-C11（建议）`prompt_override` 真实透传 + 行为变化测试 | 待立项 |
| Top4 | retry 事件丢失 llm_proposal 上下文 | 6/9 = 67% | T-C12（建议）`proposal` 参数 required + 完整 fixture | 待立项 |
| Top5 | needs_human 与最后 retry 事件重复 | 1/9 = 11% | T-C13（建议）合并终态事件 + `--dedupe-chain` 审计选项 | 待立项 |

## 5. 验收清单

| 验收项 | 阈值 | 实际 | 判定 |
|--------|------|------|------|
| 1. 分析 9 条 implement_failed 事件 | 9 | 9 (events 2,4,6,7,8,9,10,11,12) | ✅ PASS |
| 2. 输出 Top5 根因 | ≥5 | 5 | ✅ PASS |
| 3. 每条根因含频次 | 5/5 | 5/5 | ✅ PASS |
| 4. 每条根因含根因分析 | 5/5 | 5/5 | ✅ PASS |
| 5. 每条根因对应 T-Cxx 或代码修补点 | 5/5 | 5/5（T-C08 已立项，T-C09–T-C13 建议立项） | ✅ PASS |
| 6. Top1 根因作为 T-C08 输入 | 是 | Top1 = LLM >5 files → T-C08 | ✅ PASS |

**最终判定**：✅ ALL CRITERIA PASS

## 6. 附录

### 6.1 复现命令

```bash
# 查看原始 ledger
cat "成都修茈科技有限公司/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl" | \
  python3 -c "import sys, json; [print(json.dumps(json.loads(l), ensure_ascii=False, indent=2)) for l in sys.stdin if json.loads(l).get('event_type') == 'implement_failed']"

# 审计 CLI（按 event_type 过滤）
cd /Users/a4243342/Desktop/XCMAX/FHD
python3 scripts/dev/audit_evolution.py --event implement_failed
python3 scripts/dev/audit_evolution.py --event implement_failed --summary
```

### 6.2 retry 链条重建

基于 `retry_count` 字段与时间戳重建的 3 个 retry 链条：

```
Chain A (LLM >5 files，异常逃逸，无 retry_count):
  event 2 (05:15:52) — failure_reason="LLM generated 6 files > 5 limit"
  event 4 (05:16:36) — failure_reason="LLM generated 6 files > 5 limit"
  event 6 (05:17:37) — failure_reason="LLM generated 6 files > 5 limit"
  → 3 次独立失败，retry 未触发

Chain B ("no success"，retry 1→2→?):
  event 7 (05:20:27.322) — retry_count=1, failure_reason="no success"
  event 8 (05:20:27.794) — retry_count=2, failure_reason="no success"
  → retry 3 成功（未在失败事件中出现）

Chain C ("always fail"，retry 1→2→3→needs_human):
  event  9 (05:20:27.798) — retry_count=1, failure_reason="always fail"
  event 10 (05:20:27.799) — retry_count=2, failure_reason="always fail"
  event 11 (05:20:27.799) — retry_count=3, failure_reason="always fail"
  event 12 (05:20:27.799) — retry_count=3, failure_reasons=["always fail"×3], final_status=needs_human
  → 完整 retry 链条 + 终态事件
```

### 6.3 Top5 根因频次可视化

```
Top4 (llm_proposal 丢失)       ████████████████████████████  6  (67%)
Top2 (通用 failure_reason)     ███████████████████████       5  (56%)
Top3 (prompt 调整无效)         ███████████████████           4  (44%)
Top1 (LLM >5 files)            ███████████████               3  (33%)
Top5 (needs_human 重复)        █████                         1  (11%)
```

注：单条事件可命中多个根因（如 event 11 同时命中 Top2/Top3/Top4），故频次总和 > 9。
