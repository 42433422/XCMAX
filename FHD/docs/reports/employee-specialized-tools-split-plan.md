# 拆分方案：`employee_specialized_tools.py`（2674 行 → 包）

> 状态：方案（未实施）。日期 2026-06-24。
> 目标文件：`FHD/app/mod_sdk/employee_specialized_tools.py`

## 1. 为什么拆

- **2674 行**，是 `mod_sdk` 边界层里最大的单文件，远超架构守门阈值
  `scripts/arch_fitness.py:19` `MAX_FILE_LINES = 500`。
- 现在靠 `scripts/arch_fitness_baseline.txt:66` 的 `[giant-file]` 豁免硬扛着——
  属于"祖传债"，拆完即可删豁免、让该门对本文件重新生效。
- 内容上是 **13 个工具域 + 1 个 LLM-ops 巨节**揉在一起，职责清晰可分。
- ⚠️ 这是边界层文件：拆分**必须**保持对外导入路径
  `app.mod_sdk.employee_specialized_tools` 与全部公开/被测私有符号不变。

## 2. 现状盘点（实测）

- 工具实现为 **56 个顶层 `async def tool_*(params, ctx)`**，按域分节，行号见下。
- 公开面（被 `app/application/employee_runtime/executor.py:20` 与多份测试导入）：
  `handle_specialized`、`get_employee_tools`、`list_all_tool_names`、
  `TOOL_REGISTRY`、`EMPLOYEE_TOOLS`。
- **被测试 monkeypatch / 导入的私有符号**（拆分头号风险，见 §5）：
  `_check_write_gate`、`_run_cmd`、`_api_call`、`_LLM_ENV_KEYS`、
  `_PROVIDER_PROFILES`、`_MODEL_PRICES`。
- 调度 `handle_specialized` 依赖：`TOOL_REGISTRY`、`_code_write_tools()`、
  `_check_write_gate`、`_ok/_err`。

## 3. 目标结构（module → package，路径不变）

```
app/mod_sdk/employee_specialized_tools/
  __init__.py        # 仅做 re-export：把公开 + 被测私有符号挂回包顶层命名空间
  _common.py         # 路径常量、_PYTHON、_DEFAULT_*、_ok/_err、_run_cmd、_api_call
  quality.py         # L131-298  run_pytest/ruff/mutation/verify_contract 等
  git.py             # L299-334  4 个 git 工具
  deploy.py          # L335-379  pack_release/list_deploy_scripts/trigger_gh_workflow
  infra.py           # L380-444  nginx/health/mod-status/disk/logs/perf
  mods.py            # L445-522  list_mods/employee_packs/validate/duty_graph
  docs.py            # L523-573  list_docs/read_file/list_scripts
  platform.py        # L574-633  list_employees/status/action_items/autonomy
  craft.py           # L634-671  workbench_sessions/sandbox_python
  payment.py         # L672-691  check_transactions/list_invoices
  ecosystem.py       # L692-710  list_enterprise_mods/list_users
  frontend.py        # L711-769  lint/typecheck/test
  mobile.py          # L770-792  android_gradle_build
  code_write.py      # L793-924  _code_write_tools/_check_write_gate/write_file/patch_file
  llmops/            # L925-2311（≈1390 行，占全文件一半）
    __init__.py
    profiles.py      #   _PROVIDER_PROFILES（10 家）+ _LLM_ENV_KEYS/_LLM_SECRET_KEYS + provider 助手
    prices.py        #   _MODEL_PRICES（2026 价格表）
    tools.py         #   7 个 llm-ops 工具（read_llm_env_config/list_providers/test_key_health/
                     #   query_provider_usage/compare_model_prices/query_local_token_usage/query_cursor_usage）
  registry.py        # L2312-2674  TOOL_REGISTRY/EMPLOYEE_TOOLS/get_employee_tools/
                     #   list_all_tool_names/handle_specialized
```

每个域模块顶部 `from ._common import _ok, _err, _run_cmd, _api_call, _PYTHON, _FHD_ROOT, ...`。
拆完每个模块都应 ≤ 500 行（LLM-ops 再切成 profiles/prices/tools 三块以达标）。

## 4. 最高 ROI 的"半步走"（推荐先做这个）

如果不想一次全拆：**只把 `llmops/` 子包剥出去**即可。
它是自洽的（provider SSOT + 价格表 + 7 个工具，L925-2311），剥离后主文件
**2674 → ≈1300 行**，但仍 > 500——所以要真正清掉 giant-file 债，还需把剩下
13 个域至少再切一刀。务实顺序：先 `llmops/`（一半体量、零交叉依赖），其余域
按需后续再分，避免一次性大改的回归面。

## 5. 风险与硬约束（决定成败，必须照做）

1. **Monkeypatch 陷阱（头号风险）。** 多份测试这样打桩：
   `monkeypatch.setattr("app.mod_sdk.employee_specialized_tools._check_write_gate", fake)`，
   还有 `._run_cmd`、`._api_call`。拆分后这些函数搬到 `code_write.py` / `_common.py`，
   而调用点（`handle_specialized` 在 `registry.py`）若用 `from ._common import _run_cmd`
   绑定的是**导入时的引用**，打补丁包顶层的同名符号**不会生效**。
   二选一：
   - **(推荐)** 调用点改为按模块属性动态取用：`from . import _common` 后调
     `_common._run_cmd(...)`、`code_write._check_write_gate(...)`；同步把测试里 ~5 处
     patch 目标改成新模块路径（`..._common._run_cmd` 等）。诚实、无暗箱。
   - 或保持测试不变，让 `__init__` 成为唯一间接层、调度点从 `__init__` 命名空间动态解析。
     改动小但有"看不见的间接"，不如前者干净。

2. **路径深度位移（静默炸点）。** 当前 `_FHD_ROOT = Path(__file__).resolve().parents[2]`
   （文件在 `app/mod_sdk/` → parents[2] = `FHD`）。搬进包后文件变成
   `app/mod_sdk/employee_specialized_tools/_common.py`，**parents[2] 会变成 `app/mod_sdk`**。
   必须改成 `parents[3]`。`_PYTHON`/`.venv`/`_EMPLOYEES_DIR`/`_DUTY_ROSTER` 全部依赖它。

3. **保留既有延迟导入。** L796 注释明确 `tool_scope.CODE_WRITE_TOOLS` 用延迟导入避免循环；
   `code_write.py` 必须原样保留这个 lazy import。

4. **边界不外溢。** 拆分全部停留在 `app.mod_sdk` 内，不得新增对 `app.application/domain`
   的导入（现状用 httpx 调内部 API，无跨层导入，保持）。否则会撞 CI 的导入边界守门。

5. **`__init__` 必须 re-export 全部被引用符号。** 有测试 `import ... as est` 后直接用
   `est.<symbol>`；`executor.py` 用 `get_employee_tools, handle_specialized`。
   `__init__.py` 至少导出：公开 5 个 + 被测私有 6 个（见 §2）。

## 6. 实施顺序（增量、每步可回归）

1. 建包目录，整文件先原样搬进 `__init__.py`（行为零变化，跑一遍测试基线）。
2. 抽 `_common.py`，**先修 §5.2 的 parents 深度**，回跑测试。
3. 逐个抽叶子域（先简单的 git/deploy/ecosystem/mobile），每抽一个：搬函数 +
   `from ._common import ...` + 在 `registry.py` 汇总导入 → 跑测试。
4. 抽 `llmops/` 子包（最大块，profiles/prices/tools 三分）。
5. 抽 `code_write.py`（含 `_check_write_gate`，配合 §5.1）。
6. 落 `registry.py`（`TOOL_REGISTRY`/`EMPLOYEE_TOOLS`/`handle_specialized`）。
7. 补全 `__init__.py` re-export；按 §5.1 改测试 patch 目标。
8. 删 `scripts/arch_fitness_baseline.txt:66` 的 giant-file 豁免，跑 `python scripts/arch_fitness.py` 确认绿。

## 7. 验收

```bash
cd FHD
.venv/bin/python -m pytest \
  tests/test_application/test_employee_specialized_tools.py \
  tests/test_application/test_employee_specialized_tools_ext.py \
  tests/test_application/test_llm_ops_tools.py \
  tests/test_application/test_write_approval_flow.py \
  tests/test_mod_sdk/ -q
.venv/bin/python scripts/arch_fitness.py   # 应无 [giant-file] employee_specialized_tools
```
全绿 + arch-fitness 不再报该文件，即完成。
