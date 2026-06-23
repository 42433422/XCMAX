# SSOT 框架（统一注册表 + 自动派生编排器）

> **本文件为 SSOT 框架的 SSOT**。登记表位于 [config/ssot.yaml](../config/ssot.yaml)，CLI 入口位于 [scripts/dev/ssot_cli.py](../scripts/dev/ssot_cli.py)。
> 最后更新：2026-06-20

## 目的

XCMAX 项目存在多个独立 SSOT 脚本（mods、ci-workflows、coverage、version、docs-ssot），各自有独立的检查/同步命令、退出码、调用约定。本框架提供一个**轻量元层**：

- **统一注册表**：`config/ssot.yaml` 声明所有领域及其 SSOT/派生件/check/sync 命令
- **统一 CLI**：`ssot_cli.py` 提供 `list / check / sync / drift / gate / enable` 六个命令
- **插件适配器**：`scripts/dev/ssot_plugins/*.py` 包装现有脚本，**不修改原脚本**
- **MVP 只跑 check**：sync 命令对未实现插件是 inert（返回 0 + not_implemented 提示），等 P 批次落地后才生效

## 架构

```
config/ssot.yaml                    ← 唯一注册表（SSOT）：机器域 domains + 文档登记 doc_registry/retired
scripts/dev/ssot_cli.py             ← 统一 CLI 入口
scripts/dev/gen_ssot_index.py       ← 从 doc_registry/retired 生成 SSOT_INDEX.md（派生视图）
scripts/dev/ssot_plugins/
  ├── base.py                       ← 注册表加载 + 命令执行
  ├── mods.py                       ← 适配 mods_ssot.py
  ├── ci_workflows.py               ← 适配 publish_ci_workflows_to_root.py
  ├── coverage.py                   ← 适配 coverage_ratchet.py
  ├── version.py                    ← 适配 verify_version_anchors.py
  └── docs_ssot.py                  ← 适配 docs_ssot_lint.py
tests/test_dev/test_ssot_*.py       ← 16 个单元/集成测试
```

## 注册表格式（ssot.yaml）

```yaml
domains:
  - name: mods                    # 领域名（唯一）
    owner: mods-team              # 责任团队
    enabled: true                 # 是否纳入 check/gate
    ssot: FHD/mods                # SSOT 路径
    derived:                      # 派生件路径列表
      - XCAGI/mods
    mode: sync                    # 派生模式：verify|sync|generate|ratchet|lint
    check:                        # 检查命令（漂移检测）
      - python
      - scripts/dev/mods_ssot.py
      - check
    sync:                         # 同步命令（SSOT → 派生件）
      - python
      - scripts/dev/mods_ssot.py
      - sync
```

### 5 种派生模式

| 模式 | 含义 | check 行为 | sync 行为 |
|------|------|-----------|-----------|
| `verify` | 派生件必须与 SSOT 一致 | 比对内容 | 复制 SSOT → 派生件 |
| `sync` | SSOT 单向同步到派生件 | 检查漂移 | 执行同步脚本 |
| `generate` | 从 SSOT 生成派生件 | 重新生成并 diff | 重新生成并覆盖 |
| `ratchet` | 指标只升不降 | 比对当前 vs floor | 提升 floor 到当前值 |
| `lint` | SSOT 自洽性检查 | 跑 lint | 无 sync（lint 模式无写盘） |

## 文档登记表（doc_registry）→ SSOT_INDEX.md 派生

历史上存在**两个**"登记表的登记表"：机器侧 `config/ssot.yaml`（domains）与文档侧 `docs/SSOT_INDEX.md`（手维护）。两个真相源 = 没有真相源。现已收敛为一个源：

- `config/ssot.yaml` 新增 `doc_registry`（13 概念 → 唯一 SSOT 文档 + 说明）与 `retired`（已退役指针）两段，是文档登记的**唯一源**。
- `docs/SSOT_INDEX.md` 由 `scripts/dev/gen_ssot_index.py` 从上述两段**自动生成**（带"请勿手改"横幅），是派生视图。
- `scripts/dev/docs_ssot_lint.py` 直接读 `doc_registry`（不再解析 md），并校验 `SSOT_INDEX.md` 是否与 `ssot.yaml` 同步（过期则**硬失败**，不受 `--strict` 影响）。

新增/修改文档 SSOT 登记的流程：改 `ssot.yaml` 的 `doc_registry` → 跑 `python scripts/dev/gen_ssot_index.py` → 提交 `ssot.yaml` 与 `SSOT_INDEX.md`。

## CLI 命令

```bash
# 列出所有领域
python scripts/dev/ssot_cli.py list

# 检查所有 enabled 领域（漂移检测）
python scripts/dev/ssot_cli.py check
python scripts/dev/ssot_cli.py check <domain>   # 单个领域

# 同步（默认 dry-run，加 --apply 真写）
python scripts/dev/ssot_cli.py sync <domain>
python scripts/dev/ssot_cli.py sync <domain> --apply

# JSON 格式漂移报告（CI 友好）
python scripts/dev/ssot_cli.py drift

# CI 门禁：跑所有 enabled 领域，drift 则 exit 1
python scripts/dev/ssot_cli.py gate

# 启用/禁用领域
python scripts/dev/ssot_cli.py enable <domain> --on|--off
```

### 退出码

| 码 | 含义 |
|----|------|
| 0 | OK |
| 1 | DRIFT（检测到漂移） |
| 2 | CONFIG（领域不存在/已禁用） |
| 3 | EXEC（插件执行异常） |

## 当前登记领域（10 个，全部启用）

### 核心 5 域（MVP 范围，有 sync 能力）

| 领域 | 模式 | SSOT | 派生件 | check 适配 | sync 适配 |
|------|------|------|--------|-----------|-----------|
| mods | sync | FHD/mods | XCAGI/mods | mods_ssot.py check | mods_ssot.py sync ✅ |
| ci-workflows | generate | FHD/.github/workflows | .github/workflows | ci_workflows.py check（header） | publish_ci_workflows_to_root.py ✅ |
| coverage | ratchet+verify | coverage_ratchet_baseline.json | pyproject.toml + vitest.config.js | coverage_ratchet.py --check | coverage_ratchet.py --bump ✅ |
| version | sync+verify | VERSION.md | 8 处代码锚点 | verify_version_anchors.py | version_sync.py --apply ✅ |
| docs-ssot | generate | ssot.yaml（doc_registry） | SSOT_INDEX.md + 所有 md 声明 | docs_ssot_lint.py（含派生新鲜度） | gen_ssot_index.py ✅ |

### 扩展 5 域（lint/verify，advisory gate）

| 领域 | 模式 | SSOT | check 适配 | sync | 当前状态 |
|------|------|------|-----------|------|---------|
| test-files | lint | FHD/tests/ | test_files.py（禁止临时文件） | 无 | OK |
| deploy-scripts | lint | FHD/scripts/deploy/ | deploy_scripts.py（shebang/set -e） | 无 | OK（有警告） |
| deps | sync+verify | FHD/pyproject.toml | deps.py（pyproject vs requirements*.txt） | 无（需人工 reconcile） | DRIFT（31 处） |
| error-codes | lint | FHD/app/http/error_codes.py | error_codes.py（常量自洽） | 无 | OK |
| k8s-manifests | verify | FHD/k8s/ | k8s.py（SSOT vs XCAGI/k8s） | 无（derived 已弃用） | DRIFT（51 处） |

## 安全护栏

1. **dry-run 默认**：`ssot sync` 不加 `--apply` 只打印，不写盘；`version_sync.py` 默认 dry-run
2. **插件只包装不修改**：现有脚本零改动，适配器只转发调用
3. **禁用领域不参与 check/gate**：`enabled: false` 的领域被 `check/gate` 拒绝（exit 2）
4. **CI 门禁 advisory**：MVP 阶段 `ssot-drift-gate` job 使用 `continue-on-error: true`，不阻断流水线
5. **drift 输出纯净 JSON**：subprocess 输出被静默，保证 CI 可解析
6. **version_sync count=1**：只替换第一个匹配，避免 `python_version = "3.11"` 被 `version = "..."` pattern 误匹配
7. **check/sync 同源**：version_sync.py 复用 verify_version_anchors.py 的 ANCHORS 列表，保证"检测的锚点 = 同步的锚点"

## 测试

```bash
cd FHD
python -m pytest tests/test_dev/ -v
# 33 passed
```

测试覆盖：
- `test_ssot_base.py`：注册表加载、enabled 过滤、命令执行（3 tests）
- `test_ssot_cli.py`：list/check/gate/unknown domain/enabled domain（4 tests）
- `test_ssot_plugins.py`：10 个适配器 + 协议一致性（11 tests）
- `test_ssot_integration.py`：list 输出、gate 退出码、check 指定领域（3 tests）
- `test_version_sync.py`：_replace_version_in_text 纯函数、dry-run/--apply、count=1 防误匹配、ANCHORS 一致性（12 tests）

## CI 集成

`fhd-ci-cd.yml` 中新增 `ssot-drift-gate` job（advisory）：

```yaml
ssot-drift-gate:
  name: SSOT Drift Gate (advisory)
  runs-on: ubuntu-latest
  continue-on-error: true
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - run: pip install pyyaml
    - run: python FHD/scripts/dev/ssot_cli.py gate
```

## 与现有 SSOT 脚本的关系

本框架**不替代**任何现有脚本，只提供统一入口：

| 现有调用 | 等价 SSOT CLI 调用 |
|---------|-------------------|
| `python scripts/dev/mods_ssot.py check` | `python scripts/dev/ssot_cli.py check mods` |
| `python scripts/dev/coverage_ratchet.py --check` | `python scripts/dev/ssot_cli.py check coverage` |
| `python scripts/dev/verify_version_anchors.py` | `python scripts/dev/ssot_cli.py check version` |
| `python scripts/dev/docs_ssot_lint.py` | `python scripts/dev/ssot_cli.py check docs-ssot` |
| （无统一入口） | `python scripts/dev/ssot_cli.py check ci-workflows` |

现有脚本仍可独立调用，本框架是**可选的统一入口**，不破坏现有工作流。

## 后续路线

- **P3**：将 advisory gate 升级为 blocking gate（需先解决 deps/k8s-manifests 的真实漂移）
- **deps reconcile**：人工决策 requirements.txt 与 pyproject.toml 的差异（补 pyproject 或改 requirements）
- **k8s-manifests cleanup**：git rm FHD/XCAGI/k8s/（derived 已弃用，README 声明）
