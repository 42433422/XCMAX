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
config/ssot.yaml                    ← 唯一注册表（SSOT）
scripts/dev/ssot_cli.py             ← 统一 CLI 入口
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

## 当前登记领域（12 个，全部启用）

> 2026-06-23：补登记 `employee-roster` / `db-schema` 两个此前游离的真相源；
> 实测 `deps` / `k8s-manifests` 旧文档所记 31 / 51 漂移已不存在（均为 0）。

### 核心 5 域（MVP 范围，有 sync 能力）

| 领域 | 模式 | SSOT | 派生件 | check 适配 | sync 适配 |
|------|------|------|--------|-----------|-----------|
| mods | sync | FHD/mods | XCAGI/mods | mods_ssot.py check | mods_ssot.py sync ✅ |
| ci-workflows | generate | FHD/.github/workflows | .github/workflows | ci_workflows.py check（header） | publish_ci_workflows_to_root.py ✅ |
| coverage | ratchet+verify | coverage_ratchet_baseline.json | pyproject.toml + vitest.config.js | coverage_ratchet.py --check | coverage_ratchet.py --bump ✅ |
| version | sync+verify | VERSION.md | 8 处代码锚点 | verify_version_anchors.py | version_sync.py --apply ✅ |
| docs-ssot | lint | SSOT_INDEX.md | 所有 md 的 SSOT 声明 | docs_ssot_lint.py | 无（lint 模式） |

### 扩展 5 域（lint/verify，advisory gate）

| 领域 | 模式 | SSOT | check 适配 | sync | 当前状态 |
|------|------|------|-----------|------|---------|
| test-files | lint | FHD/tests/ | test_files.py（禁止临时文件） | 无 | OK |
| deploy-scripts | lint | FHD/scripts/deploy/ | deploy_scripts.py（shebang/set -e） | 无 | OK（有警告） |
| deps | sync+verify | FHD/pyproject.toml | deps.py（pyproject vs requirements*.txt） | 无（需人工 reconcile） | OK（server-api/ml 包名集合一致，0 漂移） |
| error-codes | lint | FHD/app/http/error_codes.py | error_codes.py（常量自洽） | 无 | OK |
| k8s-manifests | verify | FHD/k8s/ | k8s.py（SSOT vs XCAGI/k8s） | 无（derived 已弃用） | OK（XCAGI/k8s 已清理，0 漂移） |

### 补登记 2 域（2026-06-23，此前游离于注册表外）

| 领域 | 模式 | SSOT | check 适配 | sync | 当前状态 |
|------|------|------|-----------|------|---------|
| employee-roster | sync | FHD/config/duty_roster.json | ../scripts/dev/sync_duty_roster.py --check（4 派生目标） | ../scripts/dev/sync_duty_roster.py --generate | OK |
| db-schema | verify | FHD/alembic/versions/ | ../scripts/guard_alembic_single_head.py（单 head/无悬挂，纯 stdlib） | 无（alembic 收敛中） | OK |

> 注：`db-schema` 的完整 ORM-parity（`alembic upgrade head == models`）由独立的
> `fhd-alembic-ssot.yml` 的 `ssot-parity` job 单独把关（advisory，待一次 PG 绿后转 blocking）；
> 注册表内的 check 只做轻量结构守卫，避免 `ssot gate` 依赖 DB。

## 安全护栏

1. **dry-run 默认**：`ssot sync` 不加 `--apply` 只打印，不写盘；`version_sync.py` 默认 dry-run
2. **插件只包装不修改**：现有脚本零改动，适配器只转发调用
3. **禁用领域不参与 check/gate**：`enabled: false` 的领域被 `check/gate` 拒绝（exit 2）
4. **CI 门禁 blocking**：`ssot-drift-gate` job 已于 2026-06-23 去掉 `continue-on-error`（漂移则 exit 1 阻断流水线）。升级依据：deps/k8s 静态核实 0 漂移，version/coverage/alembic-single-head 为既有硬门（绿）；12 域全绿由本 PR 的 `ssot-drift-gate` job 在合并前终验（红则自动拦截，不会带病合入 main）
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

`fhd-ci-cd.yml` 中 `ssot-drift-gate` job（blocking）：

```yaml
ssot-drift-gate:
  name: SSOT Drift Gate
  runs-on: ubuntu-latest
  continue-on-error: false
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

- ✅ **P3 已完成（2026-06-23）**：advisory gate 升级为 blocking gate（deps/k8s 实测 0 漂移，无需 reconcile）
- ✅ **deps reconcile**：核实 server-api/ml 包名集合与 requirements*.txt 一致，0 漂移
- ✅ **k8s-manifests cleanup**：FHD/XCAGI/k8s/ 已清理（derived 弃用），插件返回 OK
- **下一步**：`db-schema` 的 alembic ssot-parity job 待一次 PG 绿后从 advisory 转 blocking（见 fhd-alembic-ssot.yml）
