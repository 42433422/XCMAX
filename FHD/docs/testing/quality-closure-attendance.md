# 太阳鸟考勤升级与 AI 评测验收

本轮修复三项已复现的问题：旧考勤库升级后跨账号同名冲突；写操作模型拦截测试假通过；LLM 评测入口缺少模块。

## 升级与数据归属

共享 `attendance-industry` Mod 升至 1.0.1。历史三表的归属列与人员/部门唯一约束在一个 SQLite 写事务中升级，保留原 ID、额外字段、索引、触发器、视图、引用和自增序列。失败时回滚；同路径恢复旧备份会重新检查。存量归属沿用现有 SUNBIRD 规则，不重新分配已有 owner。

验收包括旧库、新库、已补归属列但尚未升级约束的库。两个账号可各自添加同名人员，同账号重复返回 409，跨账号改删返回 404。测试还覆盖并发迁移与失败保留原库。代码在共享主线宿主内交付，太阳鸟转换继续使用账号授权的 `sunbird-attendance-custom`，不得制作分叉客户安装包。

## AI 评测

规则回归：`python scripts/dev/intent_benchmark.py --check`。

真实模型路由：`python scripts/dev/intent_benchmark.py --llm --output /private/path/result.json`。使用当前配置的生产路由和模型，评测不调用业务 builders 或写入工具。输出规则层与 normal router 加模型兜底层的独立成绩、源码 SHA、数据集哈希、时间、实际模型调用数、模型标识、错误类型和耗时。模型没完成调用或调用出错返回 2，不能当成通过。

独立验收集：增加 `--cases /private/path/holdout.json --min-routing-accuracy 0.90`。门槛不满足返回 1。样本使用 text 与 expected_tool/expected_primary/expected_route/check/expect_negated 等预期字段，可附 expected_slots。预期字段仅评分，不能决定路由路径。应记录样本来源并将客户来源的留出集与开发回归集分开；当前自带 97 条是开发回归集，不代表客户总体准确率。报告会包含样本文本，因此私有样本报告只保存在私有路径。

`tests/benchmarks/test_intent_benchmark_runner.py` 默认在 CI 中执行，验证入口可导入、异常不能算对、模型证据不可捏造、实际预测不由金标决定。`test_mutation_message_never_calls_llm` 通过调用计数断言验证写操作拦截，避免断言异常被业务边界捕获造成假通过。

## 一条客户流程的发布验收

1. 保存旧版安装身份、脱敏库及客户文件哈希，记录人员和部门数量；保留客户私有 Mod 及授权，不把客户数据写入主线。
2. 从已经合入 main 的准确提交构建共享宿主；检查签名、安装包 build-info、运行后端和可见 UI 的 SHA。
3. 使用旧版数据升级；核对原人员/部门/逐日记录没有丢失。分别登录两个验收账号，检查读取、同名新增、同账号重复及跨账号改删。
4. 通过太阳鸟私有转换 Mod 上传考勤源文件和模板，核对预览人数、匹配人数、目标月份，再下载输出。核对明细、月度公式和人员归属；其它账号不能下载该结果。
5. 重启后重复检查；恢复旧库副本再升级一次。确认共享宿主升级后太阳鸟授权 Mod 仍可加载和更新。

自动回归入口：`pytest tests/test_attendance/ tests/test_routes/test_attendance_industry_management.py tests/test_deep_mods/test_sunbird_conversion.py tests/test_application/test_llm_intent_gate.py tests/benchmarks/test_intent_benchmark_runner.py`。签名转换测试使用隔离账号和真实生成的 Excel；客户真实文件/安装版验收须单列，不得以该测试代替。

历史修改：#1797 账号过滤保留并补全升级约束；#1801 模型闸保留并补齐评测和有效安全断言；#1785 的共享宿主与私有 Mod 交付边界保留。其他活跃分支和依赖升级不纳入本 PR。
