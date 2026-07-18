# SSOT 框架（统一注册表 + 自动派生编排器）

> **本文件为 SSOT 框架的 SSOT**。登记表位于 [config/ssot.yaml](../config/ssot.yaml)，CLI 入口位于 [scripts/dev/ssot_cli.py](../scripts/dev/ssot_cli.py)。
> 最后更新：2026-07-18

## 目的

XCMAX 项目存在多个独立 SSOT 脚本（mods、ci-workflows、coverage、version、docs-ssot），各自有独立的检查/同步命令、退出码、调用约定。本框架提供一个**轻量元层**：

- **统一注册表**：`config/ssot.yaml` 声明所有领域及其 SSOT/派生件/check/sync 命令
- **统一 CLI**：`ssot_cli.py` 提供 `list / check / sync / drift / gate / enable` 六个命令
- **插件适配器**：`scripts/dev/ssot_plugins/*.py` 将领域检查、严格 lint 和生成件对账收回统一 gate
- **单一门禁入口**：CI 只调用 `ssot_cli.py gate`；各领域负责完整检查，不在 workflow 中重复拼第二道漂移门禁

## 架构

```
config/ssot.yaml                    ← 唯一注册表（SSOT）
scripts/dev/ssot_cli.py             ← 统一 CLI 入口
scripts/dev/ssot_plugins/*.py       ← 各领域 check/sync 适配器
scripts/dev/generate_ssot_framework.py
                                    ← 从注册表生成本文的领域清单
tests/test_dev/test_ssot_*.py       ← 单元/集成测试（数量以 pytest 实测为准）
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

## 当前登记领域（自动生成）

<!-- BEGIN GENERATED SSOT DOMAIN INVENTORY -->
> 本段由 `scripts/dev/generate_ssot_framework.py` 从 `config/ssot.yaml` 生成；请勿手改。
> 当前共 **17** 个域：**16** 个启用、**1** 个禁用。

| 领域 | 启用 | owner | 模式 | SSOT | 派生件数 | check | sync |
|---|---:|---|---|---|---:|---|---|
| mods | 是 | FHD/mod_sdk | sync | FHD/mods/ | 1 | `python scripts/dev/mods_ssot.py check` | `python scripts/dev/mods_ssot.py sync` |
| ci-workflows | 是 | ci | generate | FHD/.github/workflows/ | 1 | `python scripts/dev/ssot_plugins/ci_workflows.py check` | `python scripts/dev/ssot_plugins/ci_workflows.py sync` |
| coverage | 是 | qa | ratchet+verify | FHD/pyproject.toml#[tool.coverage.report]fail_under | 2 | `python scripts/ci/check_coverage_ssot.py` | `python scripts/dev/coverage_ratchet.py --bump` |
| version | 是 | release | sync+verify | FHD/VERSION.md | 24 | `python scripts/dev/verify_version_anchors.py` | `python scripts/dev/version_sync.py --apply` |
| docs-ssot | 是 | docs | generate+lint | FHD/docs/SSOT_INDEX.md | 1 | `python scripts/dev/ssot_plugins/docs_ssot.py check` | `python scripts/dev/generate_ssot_framework.py --apply` |
| account-system | 是 | product-platform | lint | FHD/docs/account_system_ssot.md | 9 | `python scripts/dev/ssot_plugins/account_system.py check` | `—` |
| test-files | 是 | qa | lint | FHD/tests/ | 0 | `python scripts/dev/ssot_plugins/test_files.py check` | `—` |
| deploy-scripts | 是 | devops | lint | FHD/scripts/deploy/ | 0 | `python scripts/dev/ssot_plugins/deploy_scripts.py check` | `—` |
| deps | 是 | backend | sync+verify | FHD/pyproject.toml | 2 | `python scripts/dev/ssot_plugins/deps.py check` | `—` |
| error-codes | 是 | backend | lint | FHD/app/http/error_codes.py | 0 | `python scripts/dev/ssot_plugins/error_codes.py check` | `—` |
| employee-roster | 是 | hr-platform | sync | FHD/config/duty_roster.json | 7 | `python ../scripts/dev/sync_duty_roster.py --check` | `python ../scripts/dev/sync_duty_roster.py --generate` |
| db-schema | 是 | backend | verify | FHD/alembic/versions/ | 1 | `python ../scripts/guard_alembic_single_head.py` | `—` |
| service-topology | 是 | devops | sync+verify | FHD/config/service_topology.yaml | 4 | `python scripts/dev/service_topology_ssot.py check` | `python scripts/dev/service_topology_ssot.py generate --apply` |
| deployment-modes | 是 | platform-runtime | sync+verify | FHD/config/deployment_modes.yaml | 3 | `python3 scripts/dev/deployment_modes_ssot.py check` | `python3 scripts/dev/deployment_modes_ssot.py generate --apply` |
| database-storage | 是 | platform-runtime | sync+verify | FHD/config/database_storage_modes.yaml | 2 | `python3 scripts/dev/database_storage_ssot.py check` | `python3 scripts/dev/database_storage_ssot.py generate --apply` |
| mobile-tri-platform | 是 | mobile-platform | lint | FHD/docs/mobile_tri_platform_ssot.md | 11 | `python scripts/dev/ssot_plugins/mobile_tri_platform.py check` | `—` |
| neuro-bus-events | 否 | neuro-platform | generate+verify | FHD/config/neuro_bus_events.yaml | 3 | `python scripts/dev/neuro_bus_events_ssot.py check` | `python scripts/dev/neuro_bus_events_ssot.py generate --apply` |
<!-- END GENERATED SSOT DOMAIN INVENTORY -->

## 安全护栏

1. **dry-run 默认**：`ssot sync` 不加 `--apply` 只打印，不写盘；`version_sync.py` 默认 dry-run
2. **插件只包装不修改**：现有脚本零改动，适配器只转发调用
3. **禁用领域不参与 check/gate**：`enabled: false` 的领域被 `check/gate` 拒绝（exit 2）
4. **CI 门禁 blocking**：`ssot-drift-gate` 对注册表中所有启用域执行完整检查；领域数量和状态由上方自动清单展示，不再手写数字
5. **drift 输出纯净 JSON**：subprocess 输出被静默，保证 CI 可解析
6. **version_sync count=1**：只替换第一个匹配，避免 `python_version = "3.11"` 被 `version = "..."` pattern 误匹配
7. **check/sync 同源**：version_sync.py 复用 verify_version_anchors.py 的 ANCHORS 列表，保证"检测的锚点 = 同步的锚点"

## 测试

```bash
cd FHD
python -m pytest tests/test_dev/ -v
```

测试覆盖注册表加载、CLI、各领域适配器、自动清单生成、覆盖率三层契约和版本锚点；
数量以当前 pytest 输出为准，避免在文档中复制易过期的计数。

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
| `python scripts/ci/check_coverage_ssot.py` | `python scripts/dev/ssot_cli.py check coverage` |
| `python scripts/dev/verify_version_anchors.py` | `python scripts/dev/ssot_cli.py check version` |
| `python scripts/dev/docs_ssot_lint.py --strict` + 自动清单 `--check` | `python scripts/dev/ssot_cli.py check docs-ssot` |
| `python ../scripts/dev/publish_ci_workflows_to_root.py --check` | `python scripts/dev/ssot_cli.py check ci-workflows` |

现有脚本仍可独立调用；`ssot_cli.py gate` 是 CI 的唯一聚合入口。

## 后续路线

- ✅ **P3 已完成（2026-06-23）**：advisory gate 升级为 blocking gate（deps/k8s 实测 0 漂移，无需 reconcile）
- ✅ **deps reconcile**：核实 server-api/ml 包名集合与 requirements*.txt 一致，0 漂移
- ✅ **k8s-manifests cleanup**：FHD/XCAGI/k8s/ 已清理（derived 弃用），插件返回 OK
- **下一步**：`db-schema` 的 alembic ssot-parity job 待一次 PG 绿后从 advisory 转 blocking（见 fhd-alembic-ssot.yml）
