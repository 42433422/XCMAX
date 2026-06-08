"""渲染嵌入到 .xcemp zip 内的「独立 CLI / zipapp」源文件。

生成的文件注入到 employee_pack 的 zip 中：
  __main__.py                           ← 顶层 zipapp 入口
  <import_prefix>/__init__.py
  <import_prefix>/standalone/__init__.py   （import_prefix = pack_id 合法化后的目录名，含 ``-`` 会转为 ``_``）
  <import_prefix>/standalone/cli.py           ← argparse 子命令
  <import_prefix>/standalone/runner.py        ← manifest 路由
  <import_prefix>/standalone/llm_adapter.py  ← stdlib urllib LLM 客户端
  <import_prefix>/standalone/handlers/__init__.py
  <import_prefix>/standalone/handlers/no_llm.py   ← 无 LLM 机械检查
  <import_prefix>/standalone/handlers/llm_md.py   ← 调 LLM 出 Markdown
  <import_prefix>/standalone/README.md

平台运行时只通过 <pack_id>/manifest.json 与 backend/ 加载，顶层
__main__.py 与 standalone/ 目录不参与平台路径，零侵入。
"""

from __future__ import annotations

import re


def standalone_import_prefix(pack_id: str) -> str:
    """ZIP 内 standalone 模块路径前缀：须为合法 Python 包名（pack_id 可能含 ``-``）。"""
    s = re.sub(r"[^0-9a-zA-Z_]", "_", (pack_id or "pack").strip())
    if not s:
        s = "pack"
    if s[0].isdigit():
        s = "p_" + s
    return s


def render_standalone_main_py(pack_id: str) -> str:
    """顶层 __main__.py：让 `python xxx.xcemp <cmd>` 可执行。"""
    escaped = pack_id.replace('"', '\\"')
    return f'''\
"""
zipapp 入口 — 让 .xcemp 同时是可执行 zip。

用法：
    python xxx.xcemp info
    python xxx.xcemp validate
    python xxx.xcemp run --input task.json
    python xxx.xcemp run --input task.json --llm
"""
import os
import runpy
import sys
import zipfile

# 找到 manifest.json 所在子目录即为 pack_id
_zp = sys.argv[0] if os.path.isfile(sys.argv[0]) else __file__
try:
    with zipfile.ZipFile(_zp) as _zf:
        _pack_id = next(
            n.split("/")[0]
            for n in _zf.namelist()
            if n.endswith("/manifest.json")
        )
except Exception:
    _pack_id = "{escaped}"

import re as _re

def _imp_prefix(pid: str) -> str:
    _s = _re.sub(r"[^0-9a-zA-Z_]", "_", (pid or "pack").strip())
    if not _s:
        _s = "pack"
    if _s[0].isdigit():
        _s = "p_" + _s
    return _s

_pref = _imp_prefix(_pack_id)
sys.argv[0] = f"{{_pref}}.standalone.cli"
runpy.run_module(f"{{_pref}}.standalone.cli", run_name="__main__")
'''


def render_standalone_cli_py(pack_id: str, employee_id: str, import_prefix: str) -> str:
    """argparse CLI，子命令：info / validate / run。"""
    escaped_pid = pack_id.replace('"', '\\"')
    escaped_eid = employee_id.replace('"', '\\"')
    imp = import_prefix.replace('"', '\\"')
    return f'''\
"""独立 CLI 入口 — 从 employee_pack .xcemp 中运行。"""
from __future__ import annotations

import argparse
import json
import os
import sys

PACK_ID = "{escaped_pid}"
EMPLOYEE_ID = "{escaped_eid}"


def _get_runner():
    # 当作为 zipapp 运行时，模块路径来自 zip；直接 import 即可（import_prefix 与 zip 内目录一致）
    from {imp}.standalone import runner as _r
    return _r


def cmd_info(_args):
    r = _get_runner()
    manifest = r.load_manifest()
    if manifest is None:
        print("ERROR: 无法读取 manifest.json", file=sys.stderr)
        sys.exit(1)
    print(f"id      : {{manifest.get('id', '?')}}")
    print(f"name    : {{manifest.get('name', '?')}}")
    print(f"version : {{manifest.get('version', '?')}}")
    print(f"desc    : {{str(manifest.get('description',''))[:120]}}")
    emp = manifest.get("employee") or {{}}
    print(f"employee: {{emp.get('id','?')}} / {{emp.get('label','?')}}")
    handlers = (manifest.get("actions") or {{}}).get("handlers") or []
    print(f"handlers: {{', '.join(handlers) if handlers else '(none)'}}")


def cmd_validate(_args):
    r = _get_runner()
    ok, issues = r.validate()
    if issues:
        for i in issues:
            print(f"  - {{i}}")
    if ok:
        print("validate: OK")
        sys.exit(0)
    else:
        print("validate: FAIL", file=sys.stderr)
        sys.exit(1)


def cmd_run(args):
    task_input: dict = {{}}
    if args.input:
        try:
            with open(args.input, encoding="utf-8") as f:
                task_input = json.load(f)
        except Exception as exc:
            print(f"ERROR: 读取 --input 失败: {{exc}}", file=sys.stderr)
            sys.exit(1)
    r = _get_runner()
    result = r.run(task_input, use_llm=args.llm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog=f"python {{PACK_ID}}.xcemp",
        description=f"员工包独立 CLI — {{PACK_ID}}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="打印 manifest 摘要")
    sub.add_parser("validate", help="校验 manifest 与资源（不调 LLM）")

    run_p = sub.add_parser("run", help="执行员工任务")
    run_p.add_argument(
        "--input", "-i", default=None,
        help="任务输入 JSON 文件路径（不传则用示例输入）",
    )
    run_p.add_argument(
        "--llm", action="store_true",
        help="启用 LLM 路径（需设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY）",
    )

    args = parser.parse_args()
    dispatch = {{"info": cmd_info, "validate": cmd_validate, "run": cmd_run}}
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
'''


def render_standalone_runner_py(pack_id: str, import_prefix: str) -> str:
    """读 manifest，按 actions.handlers 路由到对应 handler。"""
    escaped = pack_id.replace('"', '\\"')
    imp = import_prefix.replace('"', '\\"')
    return f'''\
"""manifest 加载 + handler 路由。"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from typing import Any, Dict, List, Optional, Tuple

PACK_ID = "{escaped}"


def _zip_path() -> Optional[str]:
    """返回正在运行的 zip 文件路径（zipapp 场景）。"""
    zp = sys.argv[0] if os.path.isfile(sys.argv[0]) else None
    if zp:
        return zp
    # 有时 __file__ 形如 /path/pack.xcemp/pack_id/standalone/runner.py
    for part in reversed(sys.path):
        if part.endswith(".xcemp") and os.path.isfile(part):
            return part
    return None


def load_manifest() -> Optional[Dict[str, Any]]:
    zp = _zip_path()
    if zp:
        try:
            with zipfile.ZipFile(zp) as zf:
                data = zf.read(f"{{PACK_ID}}/manifest.json")
                return json.loads(data.decode("utf-8"))
        except Exception:
            pass
    # 开发模式：直接读文件系统
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(here, "..", "manifest.json"),
        os.path.join(here, "..", "..", "manifest.json"),
    ]:
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                return json.load(f)
    return None


def _check_direct_python_runtime(manifest: Dict[str, Any], zp: Optional[str]) -> List[str]:
    issues: List[str] = []
    v2 = manifest.get("employee_config_v2") if isinstance(manifest.get("employee_config_v2"), dict) else {{}}
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {{}}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    if "direct_python" not in handlers:
        return issues
    direct_cfg = actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {{}}
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {{}}
    eid = str(manifest.get("id") or "").strip()
    import re as _re
    runtime_mod = _re.sub(r"[^a-z0-9_]+", "_", eid.lower()).strip("_")
    if runtime_mod.endswith("_employee"):
        runtime_mod = runtime_mod[: -len("_employee")] or runtime_mod
    convert_relpath = f"{{PACK_ID}}/backend/vendor/{{runtime_mod}}/convert.py"
    found = False
    if zp:
        try:
            with zipfile.ZipFile(zp) as zf:
                found = convert_relpath in zf.namelist()
        except Exception:
            pass
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        for _ in range(3):
            here = os.path.dirname(here)
        found = os.path.isfile(os.path.join(here, convert_relpath))
    if not found:
        issues.append(f"direct_python 运行时模块缺失: backend/vendor/{{runtime_mod}}/convert.py")
    return issues


def validate() -> Tuple[bool, List[str]]:
    issues: List[str] = []
    manifest = load_manifest()
    if manifest is None:
        return False, ["无法加载 manifest.json"]

    required = ["id", "name", "version", "artifact", "employee"]
    for k in required:
        if not manifest.get(k):
            issues.append(f"manifest 缺少字段: {{k}}")

    if manifest.get("artifact") != "employee_pack":
        issues.append("artifact 须为 employee_pack")

    emp = manifest.get("employee")
    if not isinstance(emp, dict):
        issues.append("employee 须为对象")

    handlers = (manifest.get("actions") or {{}}).get("handlers") or []
    if not handlers:
        issues.append("actions.handlers 为空（员工无可执行路径）")

    # 检查 employee_config_v2.actions.handlers
    v2 = manifest.get("employee_config_v2") if isinstance(manifest.get("employee_config_v2"), dict) else {{}}
    v2_actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {{}}
    v2_handlers = v2_actions.get("handlers") if isinstance(v2_actions.get("handlers"), list) else []
    if v2_handlers and "direct_python" in v2_handlers:
        zp = _zip_path()
        dp_issues = _check_direct_python_runtime(manifest, zp)
        issues.extend(dp_issues)

    from {imp}.standalone.handlers.no_llm import run_no_llm_checks
    extra_issues = run_no_llm_checks(manifest)
    issues.extend(extra_issues)

    return len(issues) == 0, issues


def run(task_input: Dict[str, Any], *, use_llm: bool = False) -> Dict[str, Any]:
    manifest = load_manifest()
    if manifest is None:
        return {{"ok": False, "error": "无法加载 manifest.json"}}

    handlers = (manifest.get("actions") or {{}}).get("handlers") or []

    if use_llm and "llm_md" in handlers:
        from {imp}.standalone.handlers.llm_md import run_llm_md
        return run_llm_md(manifest, task_input)

    if use_llm and "agent" in handlers:
        from {imp}.standalone.handlers.llm_md import run_llm_md
        return run_llm_md(manifest, task_input)

    from {imp}.standalone.handlers.no_llm import run_no_llm
    return run_no_llm(manifest, task_input)
'''


def render_standalone_llm_adapter_py() -> str:
    """stdlib urllib LLM HTTP 客户端，支持 OpenAI 与 DeepSeek。"""
    return '''\
"""轻量 LLM 适配器 — 仅依赖 stdlib urllib，无需安装第三方库。

支持的环境变量（按优先级）：
  OPENAI_API_KEY    → 调用 OpenAI chat completions
  DEEPSEEK_API_KEY  → 调用 DeepSeek chat completions
  OPENAI_BASE_URL   → 自定义 OpenAI 兼容端点（如 LM Studio）

若均未设置，run() 返回错误字符串而非抛异常。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


def _env_key() -> Optional[tuple]:
    """返回 (api_key, base_url, provider) 或 None。"""
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    custom_base = os.environ.get("OPENAI_BASE_URL", "").strip()

    if openai_key:
        base = custom_base or "https://api.openai.com"
        return openai_key, base.rstrip("/") + "/v1/chat/completions", "openai"
    if deepseek_key:
        return deepseek_key, "https://api.deepseek.com/v1/chat/completions", "deepseek"
    return None


def chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout: int = 60,
) -> str:
    """发送 chat completion 请求，返回 assistant 内容字符串。

    失败时返回以 "ERROR:" 开头的字符串（不抛异常）。
    """
    creds = _env_key()
    if creds is None:
        return "ERROR: 未设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY"

    api_key, url, provider = creds
    if not model:
        model = "deepseek-chat" if provider == "deepseek" else "gpt-4o-mini"

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            return "ERROR: 响应 choices 为空"
        return str(choices[0].get("message", {}).get("content") or "")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc)
        return f"ERROR: HTTP {exc.code} — {detail}"
    except Exception as exc:
        return f"ERROR: {exc}"
'''


def render_standalone_handler_no_llm_py() -> str:
    """通用无 LLM 机械检查工具（XML 格式、URL 合法性等）。"""
    return '''\
"""无 LLM 检查 handler — 适用于 manifest 结构校验与通用 XML/URL 资源检查。"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


_URL_RE = re.compile(r"^https?://[^\\s]+$")


def run_no_llm_checks(manifest: Dict[str, Any]) -> List[str]:
    """对 manifest 中声明的资产做机械检查，返回 issue 列表（空 = 无问题）。"""
    issues: List[str] = []

    # 检查 vibe_edit_ready.focus_paths 声明的文件是否存在（仅本地模式）
    actions = manifest.get("actions") or {}
    vibe_ready = actions.get("vibe_edit_ready") or {}
    focus_paths: List[str] = vibe_ready.get("focus_paths") or []
    root = vibe_ready.get("root") or "."
    for rel in focus_paths:
        if "*" in rel:
            continue  # glob 模式跳过
        full = os.path.normpath(os.path.join(root, rel))
        if not os.path.exists(full):
            issues.append(f"vibe_edit_ready 声明路径不存在: {rel}")

    # 尝试校验 manifest 中能找到的 XML 类资源（如 sitemap.xml）
    for rel in focus_paths:
        if not rel.endswith(".xml") or "*" in rel:
            continue
        full = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(full):
            try:
                ET.parse(full)
            except ET.ParseError as exc:
                issues.append(f"{rel} XML 格式错误: {exc}")

    # 校验 system_prompt 非空
    cognition = manifest.get("cognition") or manifest.get("employee_config_v2", {}).get("cognition") or {}
    agent = cognition.get("agent") or {}
    sp = agent.get("system_prompt") or ""
    if len(sp.strip()) < 50:
        issues.append("system_prompt 过短（< 50 字），可能为空或占位内容")

    return issues


def run_no_llm(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    """无 LLM 执行路径：做机械检查并输出摘要报告。"""
    issues = run_no_llm_checks(manifest)
    name = manifest.get("name") or manifest.get("id") or "unknown"
    summary_lines = [
        f"# 员工包独立检查报告 — {name}",
        "",
        f"- id: {manifest.get('id', '?')}",
        f"- version: {manifest.get('version', '?')}",
        f"- handlers: {', '.join((manifest.get('actions') or {}).get('handlers') or [])}",
        "",
    ]
    if issues:
        summary_lines.append("## 发现问题")
        for i in issues:
            summary_lines.append(f"- {i}")
    else:
        summary_lines.append("## 检查通过，未发现结构性问题。")

    # 如果任务输入包含具体的 XML 内容，尝试解析
    xml_content = task_input.get("xml_content") or task_input.get("sitemap_content")
    if xml_content:
        try:
            ET.fromstring(xml_content)
            summary_lines.append("")
            summary_lines.append("## XML 内容校验：通过")
        except ET.ParseError as exc:
            summary_lines.append("")
            summary_lines.append(f"## XML 内容校验：FAIL — {exc}")
            issues.append(f"XML 内容格式错误: {exc}")

    return {
        "ok": len(issues) == 0,
        "mode": "no_llm",
        "issues": issues,
        "summary": "\\n".join(summary_lines),
    }
'''


def render_standalone_handler_llm_md_py() -> str:
    """调 LLM 输出 Markdown 的 handler，复用 manifest 内 system_prompt。"""
    return '''\
"""LLM Markdown handler — 读 manifest 中的 system_prompt，调 LLM 输出报告。"""
from __future__ import annotations

import json
from typing import Any, Dict


def run_llm_md(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    """用 manifest 里声明的 system_prompt 向 LLM 发起单轮对话，输出 Markdown。

    需要设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY 环境变量。
    """
    # 取 system_prompt
    cognition = (
        manifest.get("cognition")
        or (manifest.get("employee_config_v2") or {}).get("cognition")
        or {}
    )
    agent_cfg = cognition.get("agent") or {}
    system_prompt = (agent_cfg.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = (
            f"你是员工「{manifest.get('name', manifest.get('id', '未知'))}」。"
            f"职责：{manifest.get('description', '（未声明）')}。"
            f"请处理用户给出的任务并以 Markdown 格式输出结果。"
        )

    # 取模型配置
    model_cfg = agent_cfg.get("model") or {}
    model_name = model_cfg.get("model_name") or None
    max_tokens = int(model_cfg.get("max_tokens") or 2048)
    temperature = float(model_cfg.get("temperature") or 0.3)

    # 构造 user message
    if task_input:
        user_msg = json.dumps(task_input, ensure_ascii=False)
    else:
        user_msg = "请对员工包进行自检，输出功能摘要与可改进点。"

    from ..llm_adapter import chat

    result = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if result.startswith("ERROR:"):
        return {
            "ok": False,
            "mode": "llm_md",
            "error": result,
            "summary": result,
        }

    return {
        "ok": True,
        "mode": "llm_md",
        "summary": result,
    }
'''


def render_standalone_readme_md(pack_id: str, employee_label: str) -> str:
    """本地用法说明 README。"""
    safe_pid = pack_id.replace("`", "'")
    safe_label = employee_label.replace("`", "'")
    return f"""\
# {safe_label} — 独立 CLI 用法

本 `.xcemp` 文件同时是一个 Python zipapp，可直接在本地运行，**不依赖 MODstore 平台**。

## 前提

- Python 3.9+
- 零第三方依赖（默认路径）
- 需要 LLM 时：设置 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY` 环境变量

## 命令

```bash
# 打印 manifest 摘要
python {safe_pid}.xcemp info

# 校验 manifest 结构与本地资源（不调 LLM）
python {safe_pid}.xcemp validate

# 执行任务（no-llm 路径，只做机械检查）
python {safe_pid}.xcemp run

# 执行任务并传入具体输入
python {safe_pid}.xcemp run --input task.json

# 启用 LLM（需设置 API Key）
python {safe_pid}.xcemp run --input task.json --llm
```

## 示例 task.json

```json
{{
  "task": "validate",
  "xml_content": "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'></urlset>"
}}
```

## 与平台的关系

| 场景 | 使用方式 |
|------|----------|
| 上架到 MODstore | 直接导入此 .xcemp 文件 |
| 本地功能验证 | `python {safe_pid}.xcemp validate` |
| CI/cron 自动检查 | `python {safe_pid}.xcemp run --input ...` |
| LLM 能力测试 | `python {safe_pid}.xcemp run --llm` |

平台运行时只读取 `{safe_pid}/manifest.json` 与 `backend/`，
`standalone/` 目录对平台完全透明，不影响任何已有功能。
"""
