# 太阳鸟固化脚本示例（solidify 产物）

`transform.py` 是固化循环的真实产物：LLM 只看「源表 workbook.json 摘要 + rules 摘要 + 金样期望 records 样例」（即 `build_solidify_prompt` 的题面），亲笔写出 `produce_records(source_workbook, rules)`，经金样门禁三轮迭代到 3842/3842 槽全匹配。

| 轮 | 成绩 | 病因与修复 |
|---|---|---|
| v1 | 68.7%（952 missing） | 原始记录取错列：「考勤时间」是应打卡时间，「打卡时间」才是实际打卡 |
| v2 | 97.8%（77 夜班多 0.5h） | 修复打卡列优先级；剩余全是每人参数问题 |
| v3 | 100% | 金样归纳每人参数（`MORNING9` / `OT_1830`，等价模板 B 列 DSL）+ 请假子列口径复现参考实现 |

端到端验收：脚本 → 规则映射员 compile → 模板写入员，与金样（太阳鸟单体 `convert_attendance_file` 输出）数据区 30240 格逐格 0 差异。

回归测试：`FHD/tests/test_mods/test_excel_rules_solidify.py::test_solidified_example_passes_golden_gate`（真实文件在本机时执行）。

要点：脚本**零 taiyangniao 依赖**（纯标准库计算，从 JSON 归纳决策树）；每人参数是当前人员配置的快照，人员变动由质检员报警后重新 solidify。
