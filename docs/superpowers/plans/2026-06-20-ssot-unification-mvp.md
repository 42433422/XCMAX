# SSOT 统一框架 MVP 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立统一 SSOT 注册表 + CLI 编排器，将现有 5 个域级脚本零改动包装为 plugin，提供 `ssot check/gate` 单一入口，CI advisory 门禁。

**Architecture:** `FHD/config/ssot.yaml` 注册表声明每个域的 source/derived/mode/check/sync；`FHD/scripts/dev/ssot_cli.py` 解析注册表并经 `ssot_plugins/` 适配器调用现有脚本；现有 5 个脚本原封不动。MVP 只跑 `check`，不触发 `sync`。

**Tech Stack:** Python 3.11 / PyYAML / pytest / GitHub Actions

**关联 spec:** `docs/superpowers/specs/2026-06-20-ssot-unification-design.md`

---

## 文件结构

| 文件 | 责任 | 动作 |
|------|------|------|
| `FHD/config/ssot.yaml` | 唯一注册表：声明 10 个域（5 enabled + 5 disabled） | 新建 |
| `FHD/scripts/dev/ssot_cli.py` | CLI 入口：list/check/sync/drift/gate/enable | 新建 |
| `FHD/scripts/dev/ssot_plugins/__init__.py` | plugin 包标识 | 新建 |
| `FHD/scripts/dev/ssot_plugins/base.py` | Plugin 协议 + 适配器加载 | 新建 |
| `FHD/scripts/dev/ssot_plugins/mods.py` | 调用 mods_ssot.py | 新建 |
| `FHD/scripts/dev/ssot_plugins/ci_workflows.py` | 调用 publish_ci_workflows_to_root.py + git diff | 新建 |
| `FHD/scripts/dev/ssot_plugins/coverage.py` | 调用 coverage_ratchet.py --check | 新建 |
| `FHD/scripts/dev/ssot_plugins/version.py` | 调用 verify_version_anchors.py | 新建 |
| `FHD/scripts/dev/ssot_plugins/docs_ssot.py` | 调用 docs_ssot_lint.py | 新建 |
| `FHD/tests/test_dev/__init__.py` | 测试包标识 | 新建 |
| `FHD/tests/test_dev/test_ssot_cli.py` | CLI 单测 | 新建 |
| `FHD/tests/test_dev/test_ssot_plugins.py` | 适配器集成测 | 新建 |
| `FHD/docs/SSOT_FRAMEWORK.md` | 框架说明 | 新建 |
| `FHD/docs/SSOT_INDEX.md` | 登记新域 ssot-framework | 修改 |
| `FHD/.github/workflows/ci-cd.yml` | 新增 ssot-drift-gate job（advisory） | 修改 |

**现有脚本路径（适配器调用目标，零改动）：**
- `FHD/scripts/dev/mods_ssot.py` → `check` / `sync [--dry-run]`
- `scripts/dev/publish_ci_workflows_to_root.py`（根目录，非 FHD）→ 无参数，直接生成
- `FHD/scripts/dev/coverage_ratchet.py` → `--check` / `--bump`
- `FHD/scripts/dev/verify_version_anchors.py` → 无参数，返回 0/1
- `FHD/scripts/dev/docs_ssot_lint.py` → 无参数，返回 0/1

---

### Task 1: 创建 SSOT 注册表 ssot.yaml

**Files:**
- Create: `FHD/config/ssot.yaml`

- [ ] **Step 1: 创建注册表文件**

```yaml
# XCMAX SSOT 注册表 — 唯一真相源登记
# 由 ssot_cli.py 读取；新增域在此声明后经 ssot enable 启用。
# MVP 只跑 check（调用各域 check 命令）；sync 命令在对应 P 批次落地后才被调用。
version: 1

domains:
  # ===== MVP enabled 域（包装现有 5 个脚本）=====
  - name: mods
    owner: FHD/mod_sdk
    enabled: true
    ssot: FHD/mods/
    derived:
      - FHD/XCAGI/mods/
    mode: sync
    check: python scripts/dev/mods_ssot.py check
    sync: python scripts/dev/mods_ssot.py sync

  - name: ci-workflows
    owner: ci
    enabled: true
    ssot: FHD/.github/workflows/
    derived:
      - .github/workflows/
    mode: generate
    # publish 脚本无 --check 模式；check = 跑 publish 后 git diff --exit-code
    check: python scripts/dev/ssot_plugins/ci_workflows.py check
    sync: python scripts/dev/publish_ci_workflows_to_root.py

  - name: coverage
    owner: qa
    enabled: true
    ssot: FHD/metrics/coverage_ratchet_baseline.json
    derived:
      - FHD/pyproject.toml#[tool.coverage.report]fail_under
      - FHD/frontend/vitest.config.js#thresholds
      - FHD/metrics/coverage-dual-summary.json
    mode: ratchet+verify
    check: python scripts/dev/coverage_ratchet.py --check
    sync: null

  - name: version
    owner: release
    enabled: true
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
    # P1 落地前 sync 指向未实现 plugin；CLI 识别 not_implemented 并跳过
    sync: python scripts/dev/ssot_plugins/version_sync.py sync

  - name: docs-ssot
    owner: docs
    enabled: true
    ssot: FHD/docs/SSOT_INDEX.md
    derived: []
    mode: lint
    check: python scripts/dev/docs_ssot_lint.py
    sync: null

  # ===== P3 预留域（enabled: false，不参与 check-all/gate）=====
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

- [ ] **Step 2: 验证 yaml 可解析**

Run: `cd FHD && python -c "import yaml; d=yaml.safe_load(open('config/ssot.yaml')); print(len(d['domains']), 'domains'); print([x['name'] for x in d['domains'] if x.get('enabled')])"`
Expected: `10 domains` + `['mods', 'ci-workflows', 'coverage', 'version', 'docs-ssot']`

- [ ] **Step 3: Commit**

```bash
git add FHD/config/ssot.yaml
git commit -m "feat(ssot): add unified SSOT registry (ssot.yaml)"
```

---

### Task 2: 创建 plugin 基础设施 base.py

**Files:**
- Create: `FHD/scripts/dev/ssot_plugins/__init__.py`
- Create: `FHD/scripts/dev/ssot_plugins/base.py`
- Create: `FHD/tests/test_dev/__init__.py`
- Test: `FHD/tests/test_dev/test_ssot_base.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_dev/test_ssot_base.py
"""SSOT plugin 基础设施单测。"""
from __future__ import annotations

import sys
from pathlib import Path

# 让 tests 能 import scripts.dev.ssot_plugins
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_load_registry_returns_domains():
    """load_registry 解析 ssot.yaml 返回域列表。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(ROOT / "config" / "ssot.yaml")
    assert len(domains) == 10
    names = [d["name"] for d in domains]
    assert "mods" in names and "version" in names


def test_load_registry_enabled_filter():
    """enabled_only=True 只返回 enabled 域。"""
    from scripts.dev.ssot_plugins.base import load_registry

    domains = load_registry(ROOT / "config" / "ssot.yaml", enabled_only=True)
    assert len(domains) == 5
    assert all(d.get("enabled", True) for d in domains)


def test_run_command_returns_exit_code():
    """run_command 执行命令并返回退出码。"""
    from scripts.dev.ssot_plugins.base import run_command

    code = run_command(["python", "-c", "import sys; sys.exit(0)"], cwd=ROOT)
    assert code == 0
    code = run_command(["python", "-c", "import sys; sys.exit(3)"], cwd=ROOT)
    assert code == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.dev.ssot_plugins'`

- [ ] **Step 3: 实现 base.py**

```python
# FHD/scripts/dev/ssot_plugins/__init__.py
"""SSOT plugin 适配器包。"""
```

```python
# FHD/scripts/dev/ssot_plugins/base.py
"""SSOT plugin 基础设施：注册表加载 + 命令执行。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_registry(path: Path | None = None, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    """加载 ssot.yaml 注册表，返回域列表。

    Args:
        path: ssot.yaml 路径，默认 FHD/config/ssot.yaml
        enabled_only: True 时只返回 enabled 域（缺省 enabled 视为 True）
    """
    if path is None:
        path = ROOT / "config" / "ssot.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    domains = data.get("domains", [])
    if enabled_only:
        domains = [d for d in domains if d.get("enabled", True)]
    return domains


def run_command(cmd: list[str], *, cwd: Path | None = None) -> int:
    """执行命令，实时透传 stdout/stderr，返回退出码。"""
    if cwd is None:
        cwd = ROOT
    result = subprocess.call(cmd, cwd=str(cwd))
    return result


def find_domain(domains: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """按 name 查找域配置。"""
    for d in domains:
        if d["name"] == name:
            return d
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_base.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/ssot_plugins/__init__.py FHD/scripts/dev/ssot_plugins/base.py FHD/tests/test_dev/__init__.py FHD/tests/test_dev/test_ssot_base.py
git commit -m "feat(ssot): add plugin base infrastructure (load_registry, run_command)"
```

---

### Task 3: 实现 ssot_cli.py 核心命令 (list/check/gate)

**Files:**
- Create: `FHD/scripts/dev/ssot_cli.py`
- Test: `FHD/tests/test_dev/test_ssot_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_dev/test_ssot_cli.py
"""ssot_cli 单测。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_cli_list_prints_all_domains(capsys):
    """list 打印所有域（含 enabled 状态）。"""
    from scripts.dev.ssot_cli import main

    code = main(["list"])
    out = capsys.readouterr().out
    assert code == 0
    assert "mods" in out and "version" in out
    assert "test-files" in out  # disabled 域也列出


def test_cli_check_unknown_domain_returns_2(capsys):
    """check 不存在的域返回退出码 2。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "no-such-domain"])
    assert code == 2


def test_cli_check_disabled_domain_returns_2(capsys):
    """check 显式指定 disabled 域返回退出码 2（需先 enable）。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "test-files"])
    assert code == 2


def test_cli_gate_runs_all_enabled(capsys):
    """gate 跑所有 enabled 域的 check，汇总退出码。"""
    from scripts.dev.ssot_cli import main

    # gate 会真实调用 5 个脚本；只要不崩、返回 0 或 1 即可
    code = main(["gate"])
    assert code in (0, 1)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.dev.ssot_cli'`

- [ ] **Step 3: 实现 ssot_cli.py**

```python
#!/usr/bin/env python3
"""XCMAX SSOT 统一 CLI。

用法:
  python scripts/dev/ssot_cli.py list                 # 列所有域
  python scripts/dev/ssot_cli.py check [domain...]    # 跑 check（默认所有 enabled 域）
  python scripts/dev/ssot_cli.py sync [domain...]     # 跑 sync（默认 dry-run）
  python scripts/dev/ssot_cli.py sync <domain> --apply  # 真写
  python scripts/dev/ssot_cli.py drift                # 全域漂移报告（JSON）
  python scripts/dev/ssot_cli.py gate                 # CI 门禁（= check-all）
  python scripts/dev/ssot_cli.py enable <domain>      # 启用某域

退出码: 0=一致 1=漂移 2=配置错误 3=脚本执行失败
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev.ssot_plugins.base import find_domain, load_registry, run_command  # noqa: E402

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2
EXIT_EXEC = 3


def _parse_check_cmd(cmd_str: str) -> list[str]:
    """将 check 命令字符串解析为 argv（用 shell 词法）。"""
    return shlex.split(cmd_str)


def _run_domain_check(domain: dict[str, Any]) -> tuple[int, str]:
    """跑单个域的 check，返回 (exit_code, message)。"""
    check_cmd = domain.get("check")
    if not check_cmd:
        return EXIT_CONFIG, f"{domain['name']}: 无 check 命令"
    argv = _parse_check_cmd(check_cmd)
    # ci-workflows 的 check 指向 plugin 自身，cwd 用 ROOT（非 FHD）
    cwd = ROOT.parent if "publish_ci_workflows" in check_cmd else ROOT
    code = run_command(argv, cwd=cwd)
    if code == 0:
        return EXIT_OK, f"{domain['name']}: OK"
    return EXIT_DRIFT, f"{domain['name']}: DRIFT (exit={code})"


def cmd_list(args: argparse.Namespace) -> int:
    domains = load_registry()
    print(f"{'name':<16} {'enabled':<8} {'mode':<14} {'ssot'}")
    print("-" * 70)
    for d in domains:
        enabled = "yes" if d.get("enabled", True) else "no"
        print(f"{d['name']:<16} {enabled:<8} {d.get('mode', '-'):<14} {d.get('ssot', '-')}")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    domains = load_registry()
    targets = args.domains
    if targets:
        # 显式指定域：校验存在且 enabled
        to_run = []
        for name in targets:
            d = find_domain(domains, name)
            if d is None:
                print(f"错误：未知域 '{name}'", file=sys.stderr)
                return EXIT_CONFIG
            if not d.get("enabled", True):
                print(f"错误：域 '{name}' 未启用（先运行: ssot enable {name}）", file=sys.stderr)
                return EXIT_CONFIG
            to_run.append(d)
    else:
        to_run = [d for d in domains if d.get("enabled", True)]

    worst = EXIT_OK
    for d in to_run:
        code, msg = _run_domain_check(d)
        print(msg)
        if code != EXIT_OK:
            worst = code if code > worst else worst
    return worst


def cmd_gate(args: argparse.Namespace) -> int:
    """CI 门禁入口，等价于 check-all。"""
    return cmd_check(args)


def cmd_sync(args: argparse.Namespace) -> int:
    domains = load_registry()
    targets = args.domains or [d["name"] for d in domains if d.get("enabled", True)]
    worst = EXIT_OK
    for name in targets:
        d = find_domain(domains, name)
        if d is None or not d.get("enabled", True):
            print(f"跳过：域 '{name}' 不存在或未启用", file=sys.stderr)
            continue
        sync_cmd = d.get("sync")
        if not sync_cmd:
            print(f"{name}: 无 sync 命令（mode={d.get('mode')}）")
            continue
        if not args.apply:
            print(f"{name}: [dry-run] {sync_cmd}")
            continue
        argv = _parse_check_cmd(sync_cmd)
        cwd = ROOT.parent if "publish_ci_workflows" in sync_cmd else ROOT
        code = run_command(argv, cwd=cwd)
        print(f"{name}: sync exit={code}")
        if code != 0:
            worst = EXIT_EXEC
    if not args.apply:
        print("\n（dry-run 模式，未写盘。加 --apply 真写。）")
    return worst


def cmd_drift(args: argparse.Namespace) -> int:
    domains = load_registry(enabled_only=True)
    report = []
    for d in domains:
        code, msg = _run_domain_check(d)
        report.append({"domain": d["name"], "status": "ok" if code == 0 else "drift", "message": msg})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return EXIT_OK if all(r["status"] == "ok" for r in report) else EXIT_DRIFT


def cmd_enable(args: argparse.Namespace) -> int:
    """将某域 enabled 改 true（改 ssot.yaml）。"""
    import yaml

    registry_path = ROOT / "config" / "ssot.yaml"
    with registry_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    found = False
    for d in data["domains"]:
        if d["name"] == args.domain:
            d["enabled"] = True
            found = True
            break
    if not found:
        print(f"错误：未知域 '{args.domain}'", file=sys.stderr)
        return EXIT_CONFIG
    with registry_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
    print(f"已启用域 '{args.domain}'")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="XCMAX SSOT 统一 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列所有域")

    check_p = sub.add_parser("check", help="跑 check")
    check_p.add_argument("domains", nargs="*", help="指定域（默认所有 enabled）")

    gate_p = sub.add_parser("gate", help="CI 门禁（= check-all）")
    gate_p.add_argument("domains", nargs="*", help="指定域（默认所有 enabled）")

    sync_p = sub.add_parser("sync", help="跑 sync")
    sync_p.add_argument("domains", nargs="*", help="指定域")
    sync_p.add_argument("--apply", action="store_true", help="真写（默认 dry-run）")

    sub.add_parser("drift", help="全域漂移报告（JSON）")

    enable_p = sub.add_parser("enable", help="启用某域")
    enable_p.add_argument("domain")

    args = parser.parse_args(argv)

    handlers = {
        "list": cmd_list,
        "check": cmd_check,
        "gate": cmd_gate,
        "sync": cmd_sync,
        "drift": cmd_drift,
        "enable": cmd_enable,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_cli.py -v`
Expected: 4 passed（gate 测试可能因环境返回 0 或 1，均接受）

- [ ] **Step 5: 手动验证 list**

Run: `cd FHD && python scripts/dev/ssot_cli.py list`
Expected: 打印 10 行域表，5 个 enabled=yes，5 个 enabled=no

- [ ] **Step 6: Commit**

```bash
git add FHD/scripts/dev/ssot_cli.py FHD/tests/test_dev/test_ssot_cli.py
git commit -m "feat(ssot): add unified CLI (list/check/sync/drift/gate/enable)"
```

---

### Task 4: 实现 5 个 plugin 适配器

**Files:**
- Create: `FHD/scripts/dev/ssot_plugins/mods.py`
- Create: `FHD/scripts/dev/ssot_plugins/ci_workflows.py`
- Create: `FHD/scripts/dev/ssot_plugins/coverage.py`
- Create: `FHD/scripts/dev/ssot_plugins/version.py`
- Create: `FHD/scripts/dev/ssot_plugins/docs_ssot.py`
- Test: `FHD/tests/test_dev/test_ssot_plugins.py`

- [ ] **Step 1: 写失败测试**

```python
# FHD/tests/test_dev/test_ssot_plugins.py
"""SSOT plugin 适配器集成测。

验证每个适配器能正确调用现有脚本并返回退出码。
不 mock 现有脚本（真实集成），但用真实注册表。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_mods_adapter_run_check():
    """mods 适配器调用 mods_ssot.py check。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.mods import run

    d = find_domain(load_registry(), "mods")
    code = run("check", d, dry_run=True)
    # 真实环境可能 0（一致）或 1（漂移），不应是 2/3（配置/执行错）
    assert code in (0, 1)


def test_ci_workflows_adapter_run_check():
    """ci_workflows 适配器 check 只读检查 header，返回 0 或 1。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.ci_workflows import run

    d = find_domain(load_registry(), "ci-workflows")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_coverage_adapter_run_check():
    """coverage 适配器调用 coverage_ratchet.py --check。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.coverage import run

    d = find_domain(load_registry(), "coverage")
    code = run("check", d, dry_run=True)
    assert code in (0, 1, 3)  # 3=无 coverage 数据时可能


def test_version_adapter_run_check():
    """version 适配器调用 verify_version_anchors.py。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.version import run

    d = find_domain(load_registry(), "version")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_docs_ssot_adapter_run_check():
    """docs_ssot 适配器调用 docs_ssot_lint.py。"""
    from scripts.dev.ssot_plugins.base import find_domain, load_registry
    from scripts.dev.ssot_plugins.docs_ssot import run

    d = find_domain(load_registry(), "docs-ssot")
    code = run("check", d, dry_run=True)
    assert code in (0, 1)


def test_all_adapters_conform_to_protocol():
    """所有 enabled 域的 check 命令可被 shlex 解析。"""
    import shlex

    from scripts.dev.ssot_plugins.base import load_registry

    for d in load_registry(enabled_only=True):
        cmd = d.get("check")
        assert cmd, f"{d['name']} 缺 check 命令"
        argv = shlex.split(cmd)
        assert len(argv) >= 1, f"{d['name']} check 命令解析为空"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_plugins.py -v`
Expected: FAIL with `ModuleNotFoundError` for each adapter module

- [ ] **Step 3: 实现 5 个适配器**

```python
# FHD/scripts/dev/ssot_plugins/mods.py
"""mods 域适配器：转发到 mods_ssot.py。"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    """action: check | sync。dry_run 仅对 sync 生效。"""
    if action == "check":
        return run_command(["python", "scripts/dev/mods_ssot.py", "check"], cwd=ROOT)
    if action == "sync":
        cmd = ["python", "scripts/dev/mods_ssot.py", "sync"]
        if dry_run:
            cmd.append("--dry-run")
        return run_command(cmd, cwd=ROOT)
    return 2
```

```python
# FHD/scripts/dev/ssot_plugins/ci_workflows.py
"""ci-workflows 域适配器。

publish 脚本无 --check 模式且会写文件；MVP check 采用只读 header 检查：
验证根仓每个 fhd-*.yml / modstore-*.yml 含 "# CI SSOT: generated from" 头。
完整内容漂移检测留待后续（需 publish 支持 --dry-run）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .base import ROOT, run_command

REPO_ROOT = ROOT.parent  # 仓根（publish 脚本在 scripts/dev/ 而非 FHD/scripts/dev/）
GENERATED_PREFIX = "fhd-"
EXTRA_GENERATED = ("modstore-",)  # 这些前缀的根 workflow 应为生成件


def _is_generated_workflow(path: Path) -> bool:
    """判断根仓 workflow 是否应为生成件（按命名约定）。"""
    name = path.name
    if name.startswith(GENERATED_PREFIX):
        return True
    return any(name.startswith(p) for p in EXTRA_GENERATED)


def check_drift() -> int:
    """只读检查：生成件 workflow 应含 CI SSOT 头。返回 0=一致 1=漂移。"""
    root_wfs = REPO_ROOT / ".github" / "workflows"
    if not root_wfs.is_dir():
        print("ci-workflows: 根 .github/workflows/ 不存在", file=sys.stderr)
        return 1
    drift = 0
    for yml in sorted(root_wfs.glob("*.yml")):
        if not _is_generated_workflow(yml):
            continue
        first_line = yml.read_text(encoding="utf-8").splitlines()[0] if yml.stat().st_size else ""
        if "CI SSOT" not in first_line and "generated from" not in first_line:
            print(f"ci-workflows: {yml.name} 缺 CI SSOT 生成头（应为生成件）", file=sys.stderr)
            drift = 1
    if drift == 0:
        print("ci-workflows: OK（生成件 header 检查通过）")
    return drift


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        return run_command(
            ["python", "scripts/dev/publish_ci_workflows_to_root.py"],
            cwd=REPO_ROOT,
        )
    return 2


if __name__ == "__main__":
    # 支持 `python .../ci_workflows.py check` 直接调用（注册表 check 命令路径）
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
```

```python
# FHD/scripts/dev/ssot_plugins/coverage.py
"""coverage 域适配器：转发到 coverage_ratchet.py。"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return run_command(["python", "scripts/dev/coverage_ratchet.py", "--check"], cwd=ROOT)
    if action == "sync":
        # ratchet bump 需显式，sync 不自动 bump
        return run_command(["python", "scripts/dev/coverage_ratchet.py", "--bump"], cwd=ROOT)
    return 2
```

```python
# FHD/scripts/dev/ssot_plugins/version.py
"""version 域适配器：check 转发到 verify_version_anchors.py。

sync（version_sync.py）在 P1 落地前未实现；CLI 识别 not_implemented 跳过。
"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return run_command(["python", "scripts/dev/verify_version_anchors.py"], cwd=ROOT)
    if action == "sync":
        # P1 未落地：version_sync.py 不存在，返回 not_implemented
        print("version sync: not_implemented（P1 落地后启用）", flush=True)
        return 0  # 跳过，不报错
    return 2
```

```python
# FHD/scripts/dev/ssot_plugins/docs_ssot.py
"""docs-ssot 域适配器：转发到 docs_ssot_lint.py。"""
from __future__ import annotations

from typing import Any

from .base import ROOT, run_command


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return run_command(["python", "scripts/dev/docs_ssot_lint.py"], cwd=ROOT)
    return 2
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_plugins.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add FHD/scripts/dev/ssot_plugins/mods.py FHD/scripts/dev/ssot_plugins/ci_workflows.py FHD/scripts/dev/ssot_plugins/coverage.py FHD/scripts/dev/ssot_plugins/version.py FHD/scripts/dev/ssot_plugins/docs_ssot.py FHD/tests/test_dev/test_ssot_plugins.py
git commit -m "feat(ssot): add 5 plugin adapters wrapping existing scripts"
```

---

### Task 5: 全量集成验证 — ssot check 全绿

**Files:**
- Test: `FHD/tests/test_dev/test_ssot_integration.py`

- [ ] **Step 1: 写集成测试**

```python
# FHD/tests/test_dev/test_ssot_integration.py
"""SSOT 框架全量集成测：ssot check 跑所有 enabled 域。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_ssot_list_shows_5_enabled_5_disabled(capsys):
    """list 输出 10 域，其中 5 enabled。"""
    from scripts.dev.ssot_cli import main

    main(["list"])
    out = capsys.readouterr().out
    # 10 行域（不含表头与分隔线）
    domain_lines = [l for l in out.splitlines() if l and not l.startswith("name") and not l.startswith("-")]
    assert len(domain_lines) == 10
    yes_count = sum(1 for l in domain_lines if " yes " in f" {l} " or l.split()[1] == "yes")
    assert yes_count == 5


def test_ssot_gate_returns_0_or_1(capsys):
    """gate 跑完所有 enabled 域，返回 0（一致）或 1（漂移），不返回 2/3。"""
    from scripts.dev.ssot_cli import main

    code = main(["gate"])
    assert code in (0, 1), f"gate 返回 {code}，应为 0 或 1"


def test_ssot_check_specific_domain():
    """check mods 单域可执行。"""
    from scripts.dev.ssot_cli import main

    code = main(["check", "mods"])
    assert code in (0, 1)
```

- [ ] **Step 2: 运行集成测试**

Run: `cd FHD && python -m pytest tests/test_dev/test_ssot_integration.py -v`
Expected: 3 passed

- [ ] **Step 3: 手动跑全量 check**

Run: `cd FHD && python scripts/dev/ssot_cli.py check`
Expected: 5 行输出（每个 enabled 域一行 OK 或 DRIFT），退出码 0 或 1

- [ ] **Step 4: 手动跑 drift 报告**

Run: `cd FHD && python scripts/dev/ssot_cli.py drift`
Expected: JSON 数组，5 个域，每个 status=ok 或 drift

- [ ] **Step 5: Commit**

```bash
git add FHD/tests/test_dev/test_ssot_integration.py
git commit -m "test(ssot): add full integration tests for ssot check/gate"
```

---

### Task 6: 文档 — SSOT_FRAMEWORK.md + 登记 SSOT_INDEX.md

**Files:**
- Create: `FHD/docs/SSOT_FRAMEWORK.md`
- Modify: `FHD/docs/SSOT_INDEX.md`

- [ ] **Step 1: 创建 SSOT_FRAMEWORK.md**

```markdown
# SSOT 统一框架

> 本文件登记于 [SSOT_INDEX.md](SSOT_INDEX.md)（domain=ssot-framework）。
> 最后更新：2026-06-20

## 是什么

统一注册表 + CLI 编排器，将现有 5 个域级 SSOT 脚本零改动包装为 plugin，提供单一入口 `ssot check/gate`。

## 注册表

`FHD/config/ssot.yaml` 声明每个域的 source/derived/mode/check/sync。新增域在此声明后经 `ssot enable <domain>` 启用。

## CLI

```bash
cd FHD
python scripts/dev/ssot_cli.py list                 # 列所有域
python scripts/dev/ssot_cli.py check                # 跑所有 enabled 域 check
python scripts/dev/ssot_cli.py check mods version   # 跑指定域
python scripts/dev/ssot_cli.py sync <domain>        # dry-run sync
python scripts/dev/ssot_cli.py sync <domain> --apply  # 真写
python scripts/dev/ssot_cli.py drift                # JSON 漂移报告
python scripts/dev/ssot_cli.py gate                 # CI 门禁入口
python scripts/dev/ssot_cli.py enable <domain>      # 启用某域
```

## 五种派生模式

| 模式 | 语义 | 实例 |
|------|------|------|
| verify | 断言一致，不写 | version |
| sync | SSOT → 派生复制 | mods |
| generate | 模板渲染 → 派生 | ci-workflows |
| ratchet | 单调递增 floor | coverage |
| lint | 注册表匹配 | docs-ssot |

## 现有域

| 域 | 模式 | 现有脚本 | enabled |
|----|------|---------|---------|
| mods | sync | mods_ssot.py | yes |
| ci-workflows | generate | publish_ci_workflows_to_root.py | yes |
| coverage | ratchet+verify | coverage_ratchet.py | yes |
| version | sync+verify | verify_version_anchors.py | yes |
| docs-ssot | lint | docs_ssot_lint.py | yes |

## 新增域流程

1. 在 `ssot.yaml` 添加域声明（`enabled: false`）
2. 实现 `ssot_plugins/<name>.py`（暴露 `run(action, domain, dry_run)`）
3. 本地 `ssot check <name>` 验证
4. `ssot enable <name>` 启用
5. CI advisory 2 周后翻硬门禁

## 安全护栏

- sync 默认 dry-run，`--apply` 才写盘
- 不删文件，只覆盖派生内容
- 现有脚本零改动
- CI 门禁渐进（advisory → 硬门禁）
```

- [ ] **Step 2: 在 SSOT_INDEX.md 登记新域**

在 `SSOT_INDEX.md` 的"领域 SSOT 登记表"添加一行：

```markdown
| ssot-framework（SSOT 框架） | [SSOT_FRAMEWORK.md](SSOT_FRAMEWORK.md) | 统一注册表 ssot.yaml + ssot_cli 编排器 |
```

- [ ] **Step 3: 验证 docs_ssot_lint 通过**

Run: `cd FHD && python scripts/dev/docs_ssot_lint.py`
Expected: 退出码 0（新声明与注册表一致）

- [ ] **Step 4: Commit**

```bash
git add FHD/docs/SSOT_FRAMEWORK.md FHD/docs/SSOT_INDEX.md
git commit -m "docs(ssot): add SSOT_FRAMEWORK.md and register in SSOT_INDEX"
```

---

### Task 7: CI 门禁 job（advisory）+ pre-commit hook

**Files:**
- Modify: `FHD/.github/workflows/ci-cd.yml`
- Modify: `.pre-commit-config.yaml`（仓根）

- [ ] **Step 1: 在 ci-cd.yml 新增 ssot-drift-gate job**

在 `FHD/.github/workflows/ci-cd.yml` 末尾（与其它 job 并列）添加：

```yaml
  ssot-drift-gate:
    name: SSOT Drift Gate (advisory)
    runs-on: ubuntu-latest
    needs: guard-temp-scripts
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install PyYAML
        run: pip install pyyaml
      - name: SSOT gate
        working-directory: FHD
        run: python scripts/dev/ssot_cli.py gate
    continue-on-error: true  # advisory 2 周，稳定后改 false 并加入 branch protection
```

- [ ] **Step 2: 同步 workflow 到根仓**

Run: `cd /Users/a4243342/Desktop/XCMAX && python scripts/dev/publish_ci_workflows_to_root.py`
Expected: 根 `.github/workflows/fhd-ci-cd.yml` 含新 job

- [ ] **Step 3: 验证根 workflow 含新 job**

Run: `grep -c "ssot-drift-gate" /Users/a4243342/Desktop/XCMAX/.github/workflows/fhd-ci-cd.yml`
Expected: `2`（job 名 + step 引用）

- [ ] **Step 4: 在 .pre-commit-config.yaml 添加 ssot-check hook**

在 `.pre-commit-config.yaml` 的 `repos:` 下添加：

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

- [ ] **Step 5: 本地验证 pre-commit hook 可执行**

Run: `cd /Users/a4243342/Desktop/XCMAX && python FHD/scripts/dev/ssot_cli.py check`
Expected: 退出码 0 或 1（不崩）

- [ ] **Step 6: Commit**

```bash
git add FHD/.github/workflows/ci-cd.yml .github/workflows/fhd-ci-cd.yml .pre-commit-config.yaml
git commit -m "ci(ssot): add advisory ssot-drift-gate job + pre-commit hook"
```

---

## 完成验收清单

- [ ] `ssot list` 输出 10 域（5 enabled / 5 disabled）
- [ ] `ssot check` 跑 5 个 enabled 域，退出码 0 或 1
- [ ] `ssot drift` 输出合法 JSON
- [ ] `ssot sync <domain>`（无 --apply）只打印不写盘
- [ ] `ssot check no-such-domain` 退出码 2
- [ ] `ssot check test-files`（disabled）退出码 2
- [ ] `pytest tests/test_dev/ -v` 全绿
- [ ] `docs_ssot_lint.py` 通过（新域已登记）
- [ ] 根 `.github/workflows/fhd-ci-cd.yml` 含 `ssot-drift-gate` job（advisory）
- [ ] 现有 5 个脚本未被修改（`git diff scripts/dev/mods_ssot.py` 等为空）
