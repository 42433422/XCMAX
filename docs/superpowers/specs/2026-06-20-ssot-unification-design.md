# SSOT 统一框架 + 自动派生 设计规格

> 日期：2026-06-20
> 状态：已批准（用户授权全决策），待实现
> 范围：XCMAX 全仓（FHD + MODstore + 企业官网）
> 关联：登记于 `FHD/docs/SSOT_INDEX.md`（domain=ssot-framework）

## 1. 背景与问题

XCMAX 已有 5 套域级 SSOT 脚本，各自独立、接口不一：

| 现有脚本 | 域 | 模式 | 接口 |
|---------|-----|------|------|
| `mods_ssot.py` | mods | sync | `sync` / `check` |
| `publish_ci_workflows_to_root.py` | ci-workflows | generate | 无子命令，直接跑 |
| `coverage_ratchet.py` | coverage | ratchet | `--check` / `--bump` |
| `verify_version_anchors.py` | version | verify | 无子命令 |
| `docs_ssot_lint.py` | docs-ssot | lint | 无子命令 |

同时存在大量未被任何 SSOT 覆盖的重复：版本号散落 6+ 处、覆盖率阈值在 4+ 文件间漂移、`_ext2/_ext3/_phase1/_phase4` 测试文件无注册表、deploy 脚本多语言同义散落、依赖清单多份、错误码硬编码、K8s 清单多份。

**目标**：建立统一注册表 + 编排器，现有脚本零改动当 plugin 调用；新域逐批 onboard；CI 渐进门禁。**核心约束：不出问题**——MVP 零行为变更，sync 默认 dry-run，不删文件，现有 CI 全绿。

## 2. 架构

### 2.1 文件布局

```
FHD/
  config/
    ssot.yaml                    # 唯一注册表（新）
    test_files_registry.yaml     # 测试文件注册表（新，P3）
  scripts/
    dev/
      ssot_cli.py                # 统一 CLI 入口（新）
      ssot_plugins/              # 现有脚本的薄适配器（新）
        __init__.py
        base.py                  # Plugin 协议定义
        mods.py
        ci_workflows.py
        coverage.py
        version.py
        docs_ssot.py
        version_sync.py          # P1 新写：版本号派生
        coverage_thresholds.py   # P2 新写：阈值派生
        test_files.py            # P3 新写：测试文件 lint
        deploy_scripts.py        # P3 新写
        deps.py                  # P3 新写
        error_codes.py           # P3 新写
        k8s.py                   # P3 新写
      # 现有脚本原封不动保留：
      mods_ssot.py
      publish_ci_workflows_to_root.py
      coverage_ratchet.py
      verify_version_anchors.py
      docs_ssot_lint.py
  docs/
    SSOT_FRAMEWORK.md            # 框架说明（新，登记进 SSOT_INDEX.md）
```

### 2.2 注册表格式 `FHD/config/ssot.yaml`

每个域声明：name、ssot（真相源路径）、derived（派生路径列表）、mode（派生模式）、check（检查命令）、sync（同步命令，可选）、owner（负责模块）。

```yaml
version: 1
domains:
  - name: mods
    owner: FHD/mod_sdk
    ssot: FHD/mods/
    derived:
      - FHD/XCAGI/mods/
    mode: sync
    check: python scripts/dev/mods_ssot.py check
    sync: python scripts/dev/mods_ssot.py sync

  - name: ci-workflows
    owner: ci
    ssot: FHD/.github/workflows/
    derived:
      - .github/workflows/
    mode: generate
    check: python scripts/dev/publish_ci_workflows_to_root.py --check
    sync: python scripts/dev/publish_ci_workflows_to_root.py

  - name: coverage
    owner: qa
    ssot: FHD/metrics/coverage_ratchet_baseline.json
    derived:
      - FHD/pyproject.toml#[tool.coverage.report]fail_under
      - FHD/frontend/vitest.config.js#thresholds
      - FHD/metrics/coverage-dual-summary.json
    mode: ratchet+verify
    check: python scripts/dev/coverage_ratchet.py --check
    sync: python scripts/dev/ssot_plugins/coverage_thresholds.py sync

  - name: version
    owner: release
    ssot: FHD/VERSION.md
    derived:
      - release/VERSION
      - 成都修茈科技有限公司/release/VERSION
      - FHD/pyproject.toml#[project]version
      - FHD/admin-console/package.json#version
      - FHD/frontend/package.json#version
      - FHD/desktop/package.json#version
    mode: sync+verify
    check: python scripts/dev/verify_version_anchors.py
    sync: python scripts/dev/ssot_plugins/version_sync.py sync

  - name: docs-ssot
    owner: docs
    ssot: FHD/docs/SSOT_INDEX.md
    derived: []
    mode: lint
    check: python scripts/dev/docs_ssot_lint.py
    sync: null

  # P3 新域（MVP 不启用，注册表预留）
  - name: test-files
    owner: qa
    enabled: false
    ssot: FHD/config/test_files_registry.yaml
    derived: []
    mode: lint
    check: python scripts/dev/ssot_plugins/test_files.py check
    sync: null

  - name: deploy-scripts
    owner: devops
    enabled: false
    ssot: FHD/scripts/deploy/
    derived: []
    mode: lint
    check: python scripts/dev/ssot_plugins/deploy_scripts.py check
    sync: null

  - name: deps
    owner: backend
    enabled: false
    ssot: FHD/pyproject.toml
    derived:
      - FHD/requirements.txt
      - FHD/requirements-ml.txt
    mode: sync+verify
    check: python scripts/dev/ssot_plugins/deps.py check
    sync: python scripts/dev/ssot_plugins/deps.py sync

  - name: error-codes
    owner: backend
    enabled: false
    ssot: FHD/app/http/error_codes.py
    derived: []
    mode: lint
    check: python scripts/dev/ssot_plugins/error_codes.py check
    sync: null

  - name: k8s-manifests
    owner: devops
    enabled: false
    ssot: FHD/k8s/
    derived:
      - FHD/XCAGI/k8s/
    mode: sync+verify
    check: python scripts/dev/ssot_plugins/k8s.py check
    sync: python scripts/dev/ssot_plugins/k8s.py sync
```

**关键字段**：
- `enabled: false`：注册但不参与 `check-all`/`gate`，P3 域默认关闭，逐个启用。
- `mode`：5 种之一或组合（`sync+verify` 表示先 sync 再 verify）。
- `derived` 路径支持 `file#section.key` 语法指向文件内字段（如 `pyproject.toml#[project]version`）；具体解析规则（TOML `[section]` 前缀 / JSON 顶层 key）在实现计划中定。
- **MVP 只跑 `check`**：注册表中 `sync` 字段可预填指向尚未实现的 plugin（如 `version_sync.py`），但 MVP 的 `ssot check`/`gate` 只调用 `check` 命令，不触发 `sync`。`sync` 命令在对应 P 批次落地后才被调用；未实现的 sync 路径被 CLI 识别为 `not_implemented` 并跳过（不报错）。

### 2.3 五种派生模式

| 模式 | 语义 | 读/写 | 现有实例 |
|------|------|------|---------|
| `verify` | 断言 SSOT 与派生一致，不写 | 只读 | verify_version_anchors |
| `sync` | SSOT → 派生文件复制/写入 | 读 SSOT + 写派生 | mods_ssot |
| `generate` | 模板渲染 SSOT → 派生 | 读 SSOT + 写派生 | publish_ci_workflows |
| `ratchet` | 单调递增 floor，只升不降 | 读当前 + 写 floor | coverage_ratchet |
| `lint` | 注册表/规则匹配，不派生 | 只读 | docs_ssot_lint |

### 2.4 CLI 接口 `ssot_cli.py`

```bash
python scripts/dev/ssot_cli.py list                    # 列所有域 + enabled 状态
python scripts/dev/ssot_cli.py check [domain...]       # 跑 check（默认所有 enabled 域）
python scripts/dev/ssot_cli.py sync [domain...]        # 跑 sync（默认 dry-run，打印 diff）
python scripts/dev/ssot_cli.py sync <domain> --apply   # 真写派生文件
python scripts/dev/ssot_cli.py drift                   # 全域漂移报告（JSON）
python scripts/dev/ssot_cli.py gate                    # CI 门禁入口（= check，非 0 退出）
python scripts/dev/ssot_cli.py enable <domain>         # 将域 enabled 改 true（改 yaml）
```

**退出码**：0 = 一致；1 = 漂移；2 = 配置错误；3 = 脚本执行失败。

### 2.5 Plugin 协议

每个 plugin 是一个可调用对象（函数或 `__main__`），接收 `action`（check/sync/dry-run）与域配置 dict，返回退出码。适配器仅转发调用现有脚本，不重写逻辑。

```python
# ssot_plugins/base.py
from typing import Protocol

class SsotPlugin(Protocol):
    def run(self, action: str, domain: dict, dry_run: bool) -> int: ...
```

现有脚本适配器示例（`ssot_plugins/mods.py`，约 20 行）：
```python
import subprocess
from pathlib import Path

def run(action, domain, dry_run):
    root = Path(__file__).resolve().parents[3]
    cmd = ["python", "scripts/dev/mods_ssot.py"]
    cmd.append("check" if action == "check" else "sync")
    if action == "sync" and dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd, cwd=root)
```

## 3. 域 onboard 计划（4 批）

| 批次 | 域 | 模式 | 新增动作 | 风险 |
|------|-----|------|---------|------|
| **MVP** | mods / ci-workflows / coverage / version / docs-ssot | 各自现有 | 仅注册 + 适配器，零行为变更 | 极低 |
| **P1** | version 扩展 | sync+verify | 新 `version_sync.py`：从 VERSION.md 派生 6 处版本号 | 低（dry-run 默认） |
| **P2** | coverage 扩展 | ratchet+verify | 扩展 check 覆盖 vitest.config + 2 个 prompt md | 低（只读 check） |
| **P3** | test-files / deploy-scripts / deps / error-codes / k8s | lint+sync | 新建注册表 + lint 脚本，`enabled:false` 逐个开 | 中（lint 可能误报） |

## 4. 安全护栏（6 条，确保不出问题）

1. **MVP 零行为变更**：第一批只加注册表 + CLI + 适配器调用现有脚本，不新增任何 sync 写入。现有 CI job 调用路径完全不变。
2. **sync 默认 dry-run**：所有 sync 命令不带 `--apply` 只打印 diff，绝不写盘。`--apply` 必须显式传入。
3. **不删文件**：sync 只覆盖派生文件内容，从不删除任何文件；退役文件需人工 `git rm`。
4. **现有脚本原封不动**：plugin 适配器只调用，不改逻辑；`mods_ssot.py check` 等现有 CI 调用路径完全不变。
5. **CI 门禁渐进**：新 `ssot-drift-gate` job 前 2 周 `continue-on-error: true`（advisory），稳定后翻硬门禁。
6. **幂等可重跑**：所有 check/sync 幂等，重复跑结果一致；失败不产生副作用（dry-run 不写，apply 写前先备份到 `.ssot-backup/`）。

## 5. CI 集成

`fhd-ci-cd.yml` 新增 job（与现有 gate 并列，不替换）：

```yaml
ssot-drift-gate:
  runs-on: ubuntu-latest
  needs: guard-temp-scripts
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.11' }
    - run: pip install pyyaml
    - run: cd FHD && python scripts/dev/ssot_cli.py gate
  continue-on-error: true   # 2 周稳定后改 false 并加入 branch protection
```

pre-commit 新增一条（仅检查变更涉及的域）：
```yaml
- repo: local
  hooks:
    - id: ssot-check
      name: SSOT drift check
      entry: python FHD/scripts/dev/ssot_cli.py check
      language: system
      pass_filenames: false
      stages: [pre-commit]
```

## 6. 成功标准

- `ssot list` 列出 5 个 enabled 域 + 5 个 disabled 域
- `ssot check` 全绿 = 现有 5 域无漂移
- `ssot drift` 报告为空 = 所有派生文件与 SSOT 一致
- `ssot sync version`（dry-run）打印 6 处版本号 diff
- `ssot sync version --apply` 后 6 处版本号全更新且 `ssot check version` 绿
- 现有 5 个脚本行为零变化，现有 CI 全绿
- 新 `ssot-drift-gate` job 在 CI 出现且 advisory 通过

## 7. 非目标（YAGNI）

- 不重写现有 5 个脚本
- 不做 Web UI / dashboard
- 不做自动 PR 修复（drift 只报告，修复人工或显式 `sync --apply`）
- 不做跨仓 SSOT（仅本仓内）
- P3 域的 lint 规则不追求完美，先拦截明显重复

## 8. 测试策略

- `ssot_cli.py` 自身单测：`tests/test_dev/test_ssot_cli.py`
  - 注册表解析、域过滤、退出码、dry-run 不写盘
- 适配器集成测：`tests/test_dev/test_ssot_plugins.py`
  - 每个适配器调用现有脚本返回码正确
- 现有脚本回归：现有 `mods_ssot.py check` 等测试保持不变，确保零回归
- CI 验证：`ssot-drift-gate` job 在 PR 上 advisory 运行

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 适配器调用现有脚本路径错误 | 中 | MVP 先在本地全跑一遍，CI advisory 2 周 |
| version_sync 误写 package.json 破坏构建 | 中 | dry-run 默认 + 写前备份 + 只改 version 字段不动其它 |
| P3 lint 误报阻断开发 | 中 | P3 域 `enabled:false`，逐个验证后再开 |
| 注册表 yaml 格式错误导致 CLI 崩 | 低 | 启动时 schema 校验，格式错退出码 2 |
| 现有脚本未来改动不通知 ssot | 低 | 适配器只转发命令，脚本接口变才需改适配器 |
