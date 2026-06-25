#!/usr/bin/env python3
"""从 FHD/mods/_employees/*/manifest.json 反向生成 yuangon 目录骨架。

每个岗位生成：
  成都修茈科技有限公司/yuangon/<area>/<pkg_id>/employee.yaml
  成都修茈科技有限公司/yuangon/<area>/<pkg_id>/README.md
  成都修茈科技有限公司/yuangon/<area>/<pkg_id>/runbook.md

运行：python FHD/scripts/dev/bootstrap_yuangon.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EMP_ROOT = REPO / "FHD" / "mods" / "_employees"
YUANGON_ROOT = REPO / "成都修茈科技有限公司" / "yuangon"

HANDLER_DOCS = {
    "llm_md": "接收 Markdown 任务描述，调用 LLM 输出结构化结果",
    "echo": "调试用：原样返回输入，用于 smoke 测试",
    "agent": "启动多步 agent 执行链",
    "shell_exec": "执行预批准的 shell 命令",
    "ssh_exec": "通过 SSH 在远端执行命令",
    "webhook": "接收外部 Webhook 推送并触发任务",
    "vibe_edit": "Vibe 代码编辑任务",
    "vibe_heal": "Vibe 代码修复任务",
    "vibe_code": "Vibe 代码生成任务",
    "doc_sync": "文档同步任务",
    "direct_python": "直接执行 Python 片段",
}

HANDOFF_HUB_DOCS: dict[str, str] = {
    "test-qa-runner": """\
### handoff: test-qa-runner → 本岗
- **触发条件**：`employee.task.done:test-qa-runner`（pytest 全绿 + coverage gate 通过）
- **输入**：CI 测试报告路径、覆盖率摘要
- **门禁**：测试红灯时本岗不得继续；回滚上游修复后重触发
""",
    "deploy-release-officer": """\
### handoff: deploy-release-officer → 本岗
- **触发条件**：`ops.change_request.approved` → deploy 执行完成
- **输入**：部署 manifest、环境 URL、健康检查结果
- **门禁**：deploy 失败时自动 rollback；本岗等待 `/healthz` 返回 200
""",
    "modstore-backend-api": """\
### handoff: modstore-backend-api → 本岗
- **触发条件**：`employee.task.done:modstore-backend-api`
- **输入**：API 端点变更 diff、OpenAPI schema 增量
- **门禁**：schema 破坏性变更需 change-request-auditor 审批后才继续
""",
    "mobile-android-release-officer": """\
### handoff: mobile-android-release-officer → 本岗（iOS 岗专用）
- **触发条件**：Android 双 SKU APK/AAB 产物就绪 + `verify_version_anchors.py` 绿
- **输入**：`release-apk/` 产物路径、build.gradle.kts 版本锚点、smoke 通过报告
- **门禁**：Android 发版未完成时 iOS 发版只允许 dry-run；版本锚点必须 10.0.0 对齐
- **当前状态**：`FHD/mobile-ios/` 已落地；`release-ios.yml` 负责 XcodeGen / simulator build / archive-export
""",
    "security-secrets-guard": """\
### handoff: security-secrets-guard → 本岗
- **触发条件**：secrets 扫描通过（gitleaks clean）
- **输入**：扫描报告、豁免列表更新
- **门禁**：新增 secret 泄露阻断本岗所有操作
""",
    "nginx-config-engineer": """\
### handoff: nginx-config-engineer → 本岗
- **触发条件**：nginx 配置审核通过 + reload 无错误
- **输入**：nginx conf diff、upstream 列表变更
- **门禁**：配置语法错误或 upstream 不可达时阻断部署
""",
}


def _make_employee_yaml(pkg_id: str, mf: dict) -> str:
    v2 = mf.get("employee_config_v2", {})
    identity = v2.get("identity", {})
    area = identity.get("area", "")
    name = identity.get("name", mf.get("name", pkg_id))
    domain = identity.get("domain", mf.get("description", ""))
    version = identity.get("version", mf.get("version", "10.0.0"))
    owner = identity.get("owner", mf.get("author", "admin"))
    wp = v2.get("workspace_policy", {})
    scope_globs = wp.get("scope_globs", [])
    forbidden_globs = wp.get("forbidden_globs", [])
    actions = v2.get("actions", {})
    handlers = actions.get("handlers", ["llm_md", "echo"])
    depends_on = mf.get("depends_on", [])
    triggers_obj = mf.get("triggers", {})
    skills_raw = v2.get("cognition", {}).get("skills", [])
    skills = [s["name"] if isinstance(s, dict) else s for s in skills_raw]

    ios_note = ""
    if pkg_id == "mobile-ios-release-officer":
        ios_note = "# NOTE: scope FHD/mobile-ios/** 已落地，release-ios.yml 为发版入口\n"

    def _quote_if_needed(s: str) -> str:
        """Quote glob strings that contain YAML-special characters."""
        if "*" in s or "?" in s or ":" in s or "{" in s or "}" in s or "[" in s or "]" in s:
            return f'"{s}"'
        return s

    def _list_yaml(items: list[str], indent: int = 2) -> str:
        pad = " " * indent
        if not items:
            return f"{pad}[]"
        return "\n".join(f"{pad}- {_quote_if_needed(i)}" for i in items)

    triggers_on_error = str(triggers_obj.get("on_error", True)).lower()
    triggers_qa_fail = str(triggers_obj.get("on_quality_fail", True)).lower()

    # Wrap domain to a single line (strip newlines) to avoid YAML block indent issues
    domain_single = " ".join(domain.split())

    lines = []
    if ios_note:
        lines.append(ios_note.rstrip())
    lines += [
        f"id: {pkg_id}",
        f"name: {name}",
        f'version: "{version}"',
        f"owner: {owner}",
        f"area: {area}",
        f"domain: >-",
        f"  {domain_single}",
        "",
        "scope_globs:",
        _list_yaml(scope_globs),
        "",
        "forbidden_globs:",
        _list_yaml(forbidden_globs),
        "",
        "depends_on:",
        _list_yaml(depends_on),
        "",
        "actions:",
        "  handlers:",
        _list_yaml(handlers, indent=4),
        "",
        "triggers:",
        f"  on_error: {triggers_on_error}",
        f"  on_quality_fail: {triggers_qa_fail}",
        "",
        "skills:",
        _list_yaml(skills),
        "",
        "changelog:",
        f'  - version: "{version}"',
        f'    date: "2026-06-07"',
        f'    note: "yuangon 骨架由 bootstrap_yuangon.py 从 manifest 反向生成（v10 线内迭代）"',
        "",
    ]
    return "\n".join(lines)


def _make_readme(pkg_id: str, mf: dict) -> str:
    v2 = mf.get("employee_config_v2", {})
    identity = v2.get("identity", {})
    name = identity.get("name", mf.get("name", pkg_id))
    domain = identity.get("domain", mf.get("description", ""))
    area = identity.get("area", "")
    depends_on = mf.get("depends_on", [])
    actions = v2.get("actions", {})
    handlers = actions.get("handlers", ["llm_md", "echo"])
    wp = v2.get("workspace_policy", {})
    scope_globs = wp.get("scope_globs", [])[:6]

    depends_list = "\n".join(f"- `{d}`" for d in depends_on) if depends_on else "- （无上游依赖）"
    handler_list = "\n".join(
        f"- `{h}`：{HANDLER_DOCS.get(h, '—')}" for h in handlers
    )
    scope_list = "\n".join(f"- `{g}`" for g in scope_globs) if scope_globs else "- （见 manifest）"

    ios_warning = ""
    if pkg_id == "mobile-ios-release-officer":
        ios_warning = "\n> **发版入口**：`FHD/mobile-ios/` 已落地，`FHD/.github/workflows/release-ios.yml` 负责 XcodeGen、模拟器构建、IPA 导出与 App Store Connect 上传。\n"

    return textwrap.dedent(f"""\
        # {name} (`{pkg_id}`)

        **area**：`{area}`  
        **yuangon 路径**：`成都修茈科技有限公司/yuangon/{area}/{pkg_id}/`
        {ios_warning}
        ## 职责

        {domain}

        ## 上游依赖 (`depends_on`)

        {depends_list}

        ## 支持的 Handlers

        {handler_list}

        ## Scope（核心文件范围）

        {scope_list}

        ## 相关链接

        - manifest：`FHD/mods/_employees/{pkg_id}/manifest.json`
        - runbook：[runbook.md](./runbook.md)

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
        """)


def _make_runbook(pkg_id: str, mf: dict) -> str:
    v2 = mf.get("employee_config_v2", {})
    identity = v2.get("identity", {})
    name = identity.get("name", mf.get("name", pkg_id))
    domain = identity.get("domain", mf.get("description", ""))
    depends_on = mf.get("depends_on", [])
    actions = v2.get("actions", {})
    handlers = actions.get("handlers", ["llm_md", "echo"])
    wp = v2.get("workspace_policy", {})
    scope_globs = wp.get("scope_globs", [])[:6]

    # Build handoff sections
    handoff_sections = []
    for dep in depends_on:
        if dep in HANDOFF_HUB_DOCS:
            handoff_sections.append(HANDOFF_HUB_DOCS[dep])
        else:
            handoff_sections.append(
                f"### handoff: {dep} → 本岗\n"
                f"- **触发条件**：`employee.task.done:{dep}`\n"
                f"- **输入**：待补充（参见 `yuangon/**/{dep}/runbook.md`）\n"
                f"- **门禁**：依赖完成前本岗不得继续\n"
            )

    handoff_text = "\n".join(handoff_sections) if handoff_sections else "（无上游依赖，直接接受 intake 派发）"

    handler_rows = "\n".join(
        f"| `{h}` | {HANDLER_DOCS.get(h, '—')} |" for h in handlers
    )

    ios_note = ""
    if pkg_id == "mobile-ios-release-officer":
        ios_note = """\

## iOS 已落地状态

`FHD/mobile-ios/` 已具备 SwiftUI 原生工程源码、XcodeGen `project.yml`、AppIcon 生成脚本、模拟器构建脚本与 App Store archive/export 脚本。本岗当前职责：

1. 维护 `FHD/mobile-ios/project.yml`、Bundle ID、entitlements、版本号与 AppIcon。
2. 维护 `FHD/.github/workflows/release-ios.yml` 的 simulator build、签名、IPA 导出和 App Store Connect 上传门禁。
3. 在 Apple 账号密钥缺失时明确报告 `IOS_TEAM_ID`、证书、profile、App Store Connect API Key 等缺口，不伪造发布成功。

"""

    scope_list = "\n".join(f"- `{g}`" for g in scope_globs) if scope_globs else "- 见 manifest"

    return textwrap.dedent(f"""\
        # Runbook：{name} (`{pkg_id}`)
        {ios_note}
        ## 职责摘要

        {domain}

        ## 上游 Handoff 契约

        {handoff_text}

        ## Handlers

        | Handler | 说明 |
        |---------|------|
        {handler_rows}

        ## 核心 Scope

        {scope_list}

        ## 故障处置

        | 场景 | 处置 |
        |------|------|
        | LLM 调用失败 | retry 2 次 → 上报 `employee.task.failed:{pkg_id}` |
        | 上游依赖未完成 | 等待 `employee.task.done:<dep>` 事件，不自行推进 |
        | scope 文件不存在 | 报告缺口，待确认后再执行，不编造路径 |
        | 版本锚点不对齐 | 运行 `verify_version_anchors.py`，修复后继续 |

        ## 验收检查清单

        - [ ] `employee.yaml.depends_on` 与 manifest 根级一致
        - [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
        - [ ] scope_globs 路径存在（或标注规划中）
        - [ ] `employee_pack_consistency_warnings` 无 handler warning
        - [ ] echo smoke 测试通过

        ---
        *本文件由 `bootstrap_yuangon.py` 生成，v10 线内迭代*
        """)


def bootstrap_all(dry_run: bool = False) -> None:
    if not EMP_ROOT.exists():
        print(f"ERROR: {EMP_ROOT} not found", file=sys.stderr)
        sys.exit(1)

    created = skipped = 0
    for emp_dir in sorted(EMP_ROOT.iterdir()):
        if not emp_dir.is_dir():
            continue
        mf_path = emp_dir / "manifest.json"
        if not mf_path.exists():
            continue
        try:
            mf = json.loads(mf_path.read_text())
        except Exception as e:
            print(f"WARN: skip {emp_dir.name} – {e}")
            continue

        pkg_id = mf.get("id", emp_dir.name)
        if not pkg_id:
            continue
        v2 = mf.get("employee_config_v2", {})
        identity = v2.get("identity", {})
        area = identity.get("area", "")
        if not area:
            print(f"SKIP {pkg_id}: no area in identity")
            skipped += 1
            continue

        target_dir = YUANGON_ROOT / area / pkg_id
        files = {
            "employee.yaml": _make_employee_yaml(pkg_id, mf),
            "README.md": _make_readme(pkg_id, mf),
            "runbook.md": _make_runbook(pkg_id, mf),
        }

        if dry_run:
            print(f"[DRY-RUN] would create {target_dir}/{{employee.yaml,README.md,runbook.md}}")
            created += 1
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            fpath = target_dir / fname
            fpath.write_text(content, encoding="utf-8")
        print(f"  created {target_dir.relative_to(REPO)}")
        created += 1

    print(f"\nDone: created={created} skipped={skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    bootstrap_all(dry_run=args.dry_run)
