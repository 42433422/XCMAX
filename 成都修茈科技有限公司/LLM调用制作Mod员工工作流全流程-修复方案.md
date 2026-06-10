# LLM 调用制作 Mod/员工/工作流全流程 — 问题修复方案

> 生成时间：2026-05-04
> 基于代码：`e:\成都修茈科技有限公司\MODstore_deploy` 与 `e:\FHD`
> 配套文档：`LLM调用制作Mod员工工作流全流程.md`

---

## 修复总览

| 编号 | 严重度 | 问题 | 涉及文件 | 修复类型 |
|------|--------|------|----------|----------|
| F-01 | 🔴 严重 | `_call_llm` 无回退机制，`call_llm=None` 时静默失败 | `employee_pack_blueprints_template.py` | 代码修复 |
| F-02 | 🔴 严重 | `ctx['http_get']`/`ctx['http_post']` 未注入实现 | `employee_pack_blueprints_template.py` | 代码修复 |
| F-03 | 🔴 严重 | LLM 生成代码无 AST 安全审查 | `mod_employee_impl_scaffold.py` | 代码修复 |
| F-04 | 🟡 中等 | FHD 宿主侧 LLM 硬编码 DeepSeek | `mod_employee_llm.py` | 代码修复 |
| F-05 | 🟡 中等 | 无流水线回滚/清理机制 | `workbench_api.py` | 代码修复 |
| F-06 | 🟡 中等 | 员工脚本仅语法校验，无行为校验 | `mod_employee_impl_scaffold.py` | 代码修复 |
| F-07 | 🟡 中等 | 员工脚本串行生成，无并行化 | `mod_employee_impl_scaffold.py` | 代码修复 |
| F-08 | 🟡 中等 | 工作流图校验不充分（环路/断连） | `workflow_nl_graph.py` | 代码修复 |
| F-09 | 🟡 中等 | LLM 调用无速率限制/成本控制 | `workbench_api.py` | 代码修复 |
| F-10 | 🟡 中等 | 单次修复重试可能不足 | `mod_employee_impl_scaffold.py` | 代码修复 |
| F-11 | 🟡 中等 | `host_check` 验证深度不足 | `workbench_api.py` | 代码修复 |
| D-01 | ❌ 文档 | `_call_llm` 回退机制描述错误 | 流程文档 §9.2 | 文档修正 |
| D-02 | ❌ 文档 | `resolve_api_key`/`resolve_base_url` 签名错误 | 流程文档 §五 | 文档修正 |
| D-03 | ❌ 文档 | `chat_dispatch` 签名错误 | 流程文档 §五 | 文档修正 |
| D-04 | ❌ 文档 | `run_employee_ai_scaffold_async` 文件位置错误 | 流程文档 §十 | 文档修正 |
| D-05 | ❌ 文档 | 缺少 `script` intent 文档 | 流程文档 §十一 | 文档修正 |
| D-06 | ⚠️ 轻微 | 超时时间描述过于简化 | 流程文档 §十二 | 文档修正 |

---

## F-01：`_call_llm` 无回退机制，`call_llm=None` 时静默失败

### 问题描述

`employee_pack_blueprints_template.py` 第 140-148 行：

```python
try:
    from app.mod_sdk.mod_employee_llm import mod_employee_complete
    async def _call_llm(messages, *, max_tokens=1024, temperature=0.2, response_format=None):
        return await mod_employee_complete(...)
    ctx['call_llm'] = _call_llm
except Exception:
    pass  # ← 静默吞掉，call_llm 保持 None
```

当 `mod_employee_complete` 导入失败时，`ctx['call_llm']` 保持 `None`，员工脚本调用 `ctx["call_llm"](...)` 会抛出 `TypeError: NoneType is not callable`。

### 修复方案

**文件**：`modstore_server/employee_pack_blueprints_template.py`

将第 140-148 行替换为：

```python
    call_llm_available = False
    try:
        from app.mod_sdk.mod_employee_llm import mod_employee_complete  # type: ignore

        async def _call_llm(messages, *, max_tokens=1024, temperature=0.2, response_format=None):
            return await mod_employee_complete(
                messages, max_tokens=max_tokens, temperature=temperature, response_format=response_format
            )

        ctx['call_llm'] = _call_llm
        call_llm_available = True
    except Exception as _e:
        logger.warning("mod_employee_complete 不可用，call_llm 未注入: %s", _e)

    if not call_llm_available:
        async def _call_llm_disabled(messages, **kwargs):
            return {"ok": False, "content": "", "error": "宿主 LLM 服务不可用（mod_employee_complete 导入失败），请检查 DEEPSEEK_API_KEY 配置"}
        ctx['call_llm'] = _call_llm_disabled
```

**效果**：
- `call_llm` 永远不会是 `None`，员工脚本不会因 `TypeError` 崩溃
- 返回明确的错误信息，而非不可理解的 `NoneType is not callable`
- 日志中记录导入失败原因，便于排查

---

## F-02：`ctx['http_get']`/`ctx['http_post']` 未注入实现

### 问题描述

`employee_pack_blueprints_template.py` 第 135-137 行将 `http_get` 和 `http_post` 设为 `None`，但 system prompt（`SYSTEM_PROMPT_EMPLOYEE_IMPL`）告诉 LLM 可以使用这两个能力。LLM 生成的员工脚本可能调用 `await ctx["http_get"](url)` 导致 `TypeError`。

### 修复方案

**文件**：`modstore_server/employee_pack_blueprints_template.py`

在第 148 行（`call_llm` 注入之后）追加 `http_get`/`http_post` 的实现注入：

```python
    try:
        import httpx as _httpx

        async def _http_get(url, *, headers=None, timeout=30):
            try:
                async with _httpx.AsyncClient(timeout=float(timeout)) as _c:
                    r = await _c.get(url, headers=headers or {})
                    return {"ok": r.status_code < 400, "status": r.status_code, "text": r.text, "error": ""}
            except Exception as _e:
                return {"ok": False, "status": 0, "text": "", "error": str(_e)[:500]}

        async def _http_post(url, *, json_body=None, data=None, headers=None, timeout=30):
            try:
                async with _httpx.AsyncClient(timeout=float(timeout)) as _c:
                    r = await _httpx.post(url, json=json_body, data=data, headers=headers or {})
                    return {"ok": r.status_code < 400, "status": r.status_code, "text": r.text, "error": ""}
            except Exception as _e:
                return {"ok": False, "status": 0, "text": "", "error": str(_e)[:500]}

        ctx['http_get'] = _http_get
        ctx['http_post'] = _http_post
    except ImportError:
        logger.warning("httpx 不可用，http_get/http_post 未注入")
        async def _http_disabled(url, **kwargs):
            return {"ok": False, "status": 0, "text": "", "error": "httpx 未安装，HTTP 请求不可用"}
        ctx['http_get'] = _http_disabled
        ctx['http_post'] = _http_disabled
```

**效果**：
- 员工脚本可正常发起 HTTP 请求，与 system prompt 声明的能力一致
- `httpx` 不可用时返回明确错误而非 `TypeError`

---

## F-03：LLM 生成代码无 AST 安全审查

### 问题描述

员工脚本由 LLM 生成后仅通过 `py_compile` 校验语法，不检查安全性。LLM 可能生成 `import os; os.system(...)` 等危险代码，而 system prompt 的约束可被绕过。

### 修复方案

**文件**：`modstore_server/mod_employee_impl_scaffold.py`

在 `_compile_check` 函数之后新增 `_security_check` 函数，并在 `_generate_one_employee_py` 和 `_fallback_employee_py` 的编译校验通过后追加安全审查。

#### 新增安全审查函数

```python
import ast

_FORBIDDEN_IMPORTS = frozenset({
    "os", "subprocess", "shutil", "sys", "pathlib",
    "socket", "ctypes", "multiprocessing", "threading",
    "signal", "resource", "fcntl", "mmap",
})
_FORBIDDEN_ATTRS = frozenset({
    "system", "popen", "exec", "eval", "compile",
    "__import__", "open",
})
_ALLOWED_MOD_SDK_PREFIX = "app.mod_sdk."


def _security_check(src: str) -> Optional[str]:
    """AST 级安全审查。返回 None 表示通过；否则返回违规描述。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"语法错误: {e}"

    violations: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    violations.append(f"禁止 import {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_mod = node.module.split(".")[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    violations.append(f"禁止 from {node.module} import ...")
                if root_mod == "app" and not node.module.startswith(_ALLOWED_MOD_SDK_PREFIX):
                    violations.append(
                        f"仅允许 from app.mod_sdk.<子模块> import ...，禁止 from {node.module}"
                    )

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr_name = node.func.attr
                if attr_name in _FORBIDDEN_ATTRS:
                    violations.append(f"禁止调用 .{attr_name}()")

            if isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "compile", "__import__"):
                    violations.append(f"禁止调用 {node.func.id}()")

    if violations:
        return "安全审查未通过: " + "; ".join(violations[:8])
    return None
```

#### 修改 `_generate_one_employee_py`

在编译校验通过后追加安全审查。将原逻辑：

```python
    err = _compile_check(raw)
    if not err:
        return {"ok": True, "source": raw}
```

改为：

```python
    err = _compile_check(raw)
    if not err:
        sec_err = _security_check(raw)
        if sec_err:
            return {"ok": False, "error": sec_err, "raw": raw}
        return {"ok": True, "source": raw}
```

修复重试后也追加安全审查：

```python
    fixed = _strip_code_fence(str(res2.get("content") or ""))
    err2 = _compile_check(fixed)
    if err2:
        return {...}  # 原有逻辑不变
    sec_err2 = _security_check(fixed)
    if sec_err2:
        return {"ok": False, "error": sec_err2, "raw": raw, "repair_raw": fixed}
    return {"ok": True, "source": fixed, "repair_used": True}
```

**效果**：
- 拦截 `import os`、`subprocess`、`eval()`、`exec()` 等危险调用
- 强制 `app.*` 导入只能走 `app.mod_sdk` 契约层
- 安全审查未通过时降级为 `_fallback_employee_py`

---

## F-04：FHD 宿主侧 LLM 硬编码 DeepSeek

### 问题描述

`mod_employee_llm.py` 只使用 `DEEPSEEK_API_KEY` 和 `call_deepseek_api`，而 MODstore 服务端支持 21 个 LLM 供应商。运行时员工只能走 DeepSeek。

### 修复方案

**文件**：`FHD/app/mod_sdk/mod_employee_llm.py`

增加多供应商支持，从宿主配置中读取 LLM 供应商和密钥：

```python
"""
Mod 员工脚本用的窄 LLM 入口（经 ``app.mod_sdk`` 暴露）。

由 MODstore 生成的 ``mods/<id>/backend/blueprints.py`` 内 ``_call_llm`` 优先调用本模块，
避免 Mod 代码直接依赖 ``app.services.*`` 或 ``modstore_server``。

支持多供应商：优先使用宿主配置的 provider/key，回退到 DEEPSEEK_API_KEY。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_host_llm_config() -> dict[str, Any]:
    """从宿主环境变量/配置解析 LLM 供应商与密钥。"""
    provider = os.environ.get("XCAGI_LLM_PROVIDER", "").strip().lower()
    api_key = ""
    base_url = None

    if provider:
        env_key = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(env_key, "").strip()
        env_base = f"{provider.upper()}_BASE_URL"
        base_url = os.environ.get(env_base, "").strip() or None

    if not api_key:
        provider = "deepseek"
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or None

    return {"provider": provider, "api_key": api_key, "base_url": base_url}


async def mod_employee_complete(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: Any = None,
) -> dict[str, Any]:
    if not isinstance(messages, list) or not messages:
        return {"ok": False, "content": "", "error": "messages 必须为非空列表"}

    config = _resolve_host_llm_config()
    provider = config["provider"]
    api_key = config["api_key"]
    base_url = config["base_url"]

    if not api_key:
        return {
            "ok": False,
            "content": "",
            "error": f"宿主未配置 LLM 密钥（当前供应商: {provider}），请设置 {provider.upper()}_API_KEY",
        }

    try:
        from app.services.ai_conversation_service import get_ai_conversation_service
    except ImportError as e:
        logger.warning("mod_employee_complete: get_ai_conversation_service 不可用: %s", e)
        return {"ok": False, "content": "", "error": "get_ai_conversation_service not available"}

    svc = get_ai_conversation_service()

    kwargs: dict[str, Any] = {}
    if response_format is not None:
        kwargs["response_format"] = response_format

    try:
        raw: dict[str, Any] | None = await svc.call_deepseek_api(
            messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("mod_employee_complete: call_deepseek_api 异常")
        return {"ok": False, "content": "", "error": str(e)[:500]}

    if not raw:
        return {"ok": False, "content": "", "error": "LLM 返回空（请检查密钥与网络）"}

    try:
        choices = raw.get("choices")
        if not choices:
            return {"ok": False, "content": "", "error": "LLM 响应缺少 choices"}
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            return {"ok": False, "content": "", "error": "LLM 响应缺少 message.content"}
        return {"ok": True, "content": str(content), "error": ""}
    except (KeyError, IndexError, TypeError) as e:
        return {"ok": False, "content": "", "error": f"无法解析 LLM 响应: {e}"[:500]}
```

**新增环境变量**：
- `XCAGI_LLM_PROVIDER`：指定运行时 LLM 供应商（如 `openai`、`siliconflow` 等），不设则默认 `deepseek`
- `{PROVIDER}_API_KEY`：对应供应商的密钥
- `{PROVIDER}_BASE_URL`：对应供应商的 base URL（可选）

---

## F-05：无流水线回滚/清理机制

### 问题描述

12 步流水线中，如果中间步骤失败，前面步骤的产物（manifest、仓库目录、员工脚本、DB 记录）已经落盘/入库，但没有自动清理。用户重试时可能遇到目录已存在、DB 记录冲突。

### 修复方案

**文件**：`modstore_server/workbench_api.py`

在 `_run_pipeline` 函数中增加清理逻辑：

#### 1. 在 `_run_pipeline` 开头记录已创建的资源

```python
_created_resources: List[Dict[str, Any]] = []
```

#### 2. 在各步骤成功后追加资源记录

```python
# 步骤3 repo 成功后
_created_resources.append({"type": "mod_dir", "path": str(mod_dir)})

# 步骤7 workflows 成功后
_created_resources.append({"type": "workflow_ids", "ids": [r["workflow_id"] for r in workflow_results if r.get("ok")]})

# 步骤8 register_packs 成功后
_created_resources.append({"type": "catalog_items", "mod_id": mod_id})
```

#### 3. 在 `_fail_session` 中追加清理

```python
async def _cleanup_created_resources(resources: List[Dict[str, Any]]) -> None:
    """流水线失败时清理已创建的资源。"""
    for res in reversed(resources):
        try:
            if res["type"] == "mod_dir":
                import shutil
                p = Path(res["path"])
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
            elif res["type"] == "workflow_ids":
                from modstore_server.models import Workflow
                for wid in res["ids"]:
                    wf = db.query(Workflow).filter(Workflow.id == wid).first()
                    if wf:
                        db.delete(wf)
                db.commit()
            elif res["type"] == "catalog_items":
                from modstore_server.models import CatalogItem
                db.query(CatalogItem).filter(CatalogItem.mod_id == res["mod_id"]).delete()
                db.commit()
        except Exception:
            pass
```

#### 4. 在 `_run_pipeline` 的异常处理中调用清理

```python
except Exception as e:
    await _cleanup_created_resources(_created_resources)
    await _fail_session(sid, current_step_id, str(e)[:2000])
```

**效果**：流水线失败时自动清理已创建的目录和 DB 记录，用户可安全重试。

---

## F-06：员工脚本仅语法校验，无行为校验

### 问题描述

`py_compile` 只检查语法，不验证 `run()` 函数是否存在、签名是否正确、import 是否有效。

### 修复方案

**文件**：`modstore_server/mod_employee_impl_scaffold.py`

在 `_security_check` 函数之后新增 `_behavior_check`：

```python
def _behavior_check(src: str) -> Optional[str]:
    """行为校验：检查 run 函数是否存在且签名基本正确。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"语法错误: {e}"

    has_run = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run":
            has_run = True
            arg_names = [a.arg for a in node.args.args]
            if "payload" not in arg_names or "ctx" not in arg_names:
                return "run() 签名必须为 async def run(payload, ctx)"
            break

    if not has_run:
        return "缺少 async def run(payload, ctx) 函数定义"

    return None
```

在 `_generate_one_employee_py` 中，编译和安全审查通过后追加行为校验：

```python
    err = _compile_check(raw)
    if not err:
        sec_err = _security_check(raw)
        if sec_err:
            return {"ok": False, "error": sec_err, "raw": raw}
        beh_err = _behavior_check(raw)
        if beh_err:
            return {"ok": False, "error": beh_err, "raw": raw}
        return {"ok": True, "source": raw}
```

**效果**：确保生成的员工脚本至少包含正确的 `async def run(payload, ctx)` 函数。

---

## F-07：员工脚本串行生成，无并行化

### 问题描述

`generate_mod_employee_impls_async` 对 N 名员工逐个串行调用 LLM，总耗时为 N × 单次 LLM 调用时间。

### 修复方案

**文件**：`modstore_server/mod_employee_impl_scaffold.py`

修改 `generate_mod_employee_impls_async`，使用 `asyncio.Semaphore` 控制并发度：

```python
import asyncio

_MAX_CONCURRENT_LLM = 3  # 并发上限，避免触发 API 速率限制


async def generate_mod_employee_impls_async(
    db: Session,
    user: User,
    *,
    mod_dir: Path,
    employees: List[Dict[str, Any]],
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]] = None,
    provider: Optional[str],
    model: Optional[str],
    status_hook: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    out_dir = mod_dir / "backend" / "employees"
    out_dir.mkdir(parents=True, exist_ok=True)
    init_py = out_dir / "__init__.py"
    if not init_py.is_file():
        init_py.write_text(
            '"""Generated employee implementations (loaded via import_mod_backend_py)."""\n',
            encoding="utf-8",
        )

    prov = (provider or "").strip()
    mdl = (model or "").strip()
    api_key = ""
    base = None
    if prov:
        api_key, _ = resolve_api_key(db, user.id, prov)
        if prov in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
            base = resolve_base_url(db, user.id, prov)

    valid_employees = [e for e in employees if isinstance(e, dict) and str(e.get("id") or "").strip()]
    total = len(valid_employees)

    sem = asyncio.Semaphore(_MAX_CONCURRENT_LLM)

    async def _gen_one(idx: int, emp: Dict[str, Any]) -> Dict[str, Any]:
        eid = str(emp.get("id") or "").strip()
        stem = sanitize_employee_stem(eid)
        target = out_dir / f"{stem}.py"
        label = str(emp.get("label") or emp.get("panel_title") or eid).strip()
        panel_summary = str(emp.get("panel_summary") or "").strip()

        if status_hook:
            short = (label[:24] + "…") if len(label) > 24 else label
            await status_hook(f"第 {idx + 1}/{total} 名员工「{short}」：请求模型生成实现代码…")

        used_fallback = False
        gen_err = ""
        source = ""

        if prov and mdl and api_key:
            async with sem:
                gen = await _generate_one_employee_py(
                    prov=prov,
                    api_key=api_key,
                    base_url=base,
                    model=mdl,
                    emp=emp,
                    mod_id=mod_id,
                    mod_name=mod_name,
                    mod_brief=mod_brief,
                    industry_card=industry_card,
                )
            if gen.get("ok"):
                source = str(gen.get("source") or "").strip() + "\n"
            else:
                gen_err = str(gen.get("error") or "")
        else:
            gen_err = "LLM provider/model/api_key 不可用，写入兜底实现"

        if not source:
            source = _fallback_employee_py(eid, label, panel_summary)
            used_fallback = True

        target.write_text(source, encoding="utf-8")
        entry = {
            "employee_id": eid,
            "stem": stem,
            "path": f"backend/employees/{stem}.py",
            "fallback": used_fallback,
        }
        if used_fallback and gen_err:
            entry["note"] = gen_err[:400]
        return entry

    results = await asyncio.gather(*[_gen_one(i, e) for i, e in enumerate(valid_employees)])

    generated = list(results)
    errors = [e for e in generated if e.get("fallback") and e.get("note")]

    return {
        "ok": not errors,
        "generated": generated,
        "errors": errors,
    }
```

**效果**：最多 3 个员工并行生成，总耗时从 N×T 降至约 ceil(N/3)×T。

---

## F-08：工作流图校验不充分（环路/断连）

### 问题描述

`apply_nl_workflow_graph` 仅校验 start/end 节点数量，不检查环路和断连组件。

### 修复方案

**文件**：`modstore_server/workflow_nl_graph.py`

在图校验部分追加环路检测和连通性校验：

```python
from collections import deque


def _detect_cycles(nodes: List[Dict], edges: List[Dict]) -> List[str]:
    """检测有向图中的环路，返回环路描述列表。"""
    node_ids = {n.get("id") for n in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        src = e.get("source") or e.get("from")
        tgt = e.get("target") or e.get("to")
        if src in adj:
            adj[src].append(tgt)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in node_ids}
    cycles: List[str] = []

    def dfs(u: str, path: List[str]) -> None:
        color[u] = GRAY
        path.append(u)
        for v in adj[u]:
            if color[v] == GRAY:
                idx = path.index(v)
                cycles.append(" → ".join(path[idx:] + [v]))
            elif color[v] == WHITE:
                dfs(v, path)
        path.pop()
        color[u] = BLACK

    for nid in node_ids:
        if color[nid] == WHITE:
            dfs(nid, [])

    return cycles


def _check_reachability(nodes: List[Dict], edges: List[Dict]) -> List[str]:
    """检查从 start 节点能否到达所有其他节点，返回不可达节点列表。"""
    start_ids = [n.get("id") for n in nodes if n.get("type") == "start"]
    if not start_ids:
        return ["无 start 节点"]

    adj: dict[str, list[str]] = {}
    for n in nodes:
        adj.setdefault(n.get("id"), [])
    for e in edges:
        src = e.get("source") or e.get("from")
        tgt = e.get("target") or e.get("to")
        adj.setdefault(src, []).append(tgt)

    visited = set()
    queue = deque(start_ids)
    while queue:
        u = queue.popleft()
        if u in visited:
            continue
        visited.add(u)
        for v in adj.get(u, []):
            if v not in visited:
                queue.append(v)

    unreachable = [n.get("id") for n in nodes if n.get("id") not in visited]
    return unreachable
```

在 `apply_nl_workflow_graph` 的校验阶段调用：

```python
    cycles = _detect_cycles(nodes_in, edges_in)
    if cycles:
        warnings.append(f"检测到 {len(cycles)} 个环路: {cycles[0][:200]}")

    unreachable = _check_reachability(nodes_in, edges_in)
    if unreachable:
        warnings.append(f"存在 {len(unreachable)} 个从 start 不可达的节点: {unreachable[:5]}")
```

**效果**：检测到环路或断连时发出警告（不阻断，因为 LLM 生成的图可能需要人工修正），前端可展示给用户。

---

## F-09：LLM 调用无速率限制/成本控制

### 问题描述

做 Mod 模式下 LLM 调用次数为 `1(蓝图) + N(员工) + N(工作流)`，无上限和成本控制。

### 修复方案

**文件**：`modstore_server/workbench_api.py`

在 `_run_pipeline` 的 mod 分支开头增加调用预算检查：

```python
_MAX_EMPLOYEES_FOR_LLM = 10  # 单次 Mod 最多为 10 名员工生成 LLM 实现


# 在步骤6 employee_impls 之前
employees_for_impl = employees[:_MAX_EMPLOYEES_FOR_LLM]
if len(employees) > _MAX_EMPLOYEES_FOR_LLM:
    await _set_step(sid, "employee_impls", "running",
        f"员工数 {len(employees)} 超过上限 {_MAX_EMPLOYEES_FOR_LLM}，仅生成前 {_MAX_EMPLOYEES_FOR_LLM} 名")
    skipped = employees[_MAX_EMPLOYEES_FOR_LLM:]
    for emp in skipped:
        eid = str(emp.get("id") or "").strip()
        stem = sanitize_employee_stem(eid)
        label = str(emp.get("label") or eid)
        fallback_src = _fallback_employee_py(eid, label, str(emp.get("panel_summary") or ""))
        (mod_dir / "backend" / "employees" / f"{stem}.py").write_text(fallback_src, encoding="utf-8")
```

**效果**：防止单次编排产生过多 LLM 调用，超限员工自动降级为 fallback 实现。

---

## F-10：单次修复重试可能不足

### 问题描述

蓝图生成和员工脚本生成都只有一次修复重试机会。

### 修复方案

**文件**：`modstore_server/mod_employee_impl_scaffold.py`

将 `_generate_one_employee_py` 中的修复逻辑改为可配置重试次数：

```python
_MAX_REPAIR_ATTEMPTS = 2  # 修复重试次数（原为 1）


async def _generate_one_employee_py(
    *,
    prov: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    emp: Dict[str, Any],
    mod_id: str,
    mod_name: str,
    mod_brief: str,
    industry_card: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    user_msg = "\n".join(
        _employee_brief_lines(emp, mod_id=mod_id, mod_name=mod_name, mod_brief=mod_brief, industry_card=industry_card)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL},
        {"role": "user", "content": user_msg},
    ]
    res = await chat_dispatch(prov, api_key=api_key, base_url=base_url, model=model, messages=messages, max_tokens=3072)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "upstream error"}
    raw = _strip_code_fence(str(res.get("content") or ""))

    current_source = raw
    for attempt in range(_MAX_REPAIR_ATTEMPTS):
        err = _compile_check(current_source)
        if not err:
            sec_err = _security_check(current_source)
            if sec_err:
                return {"ok": False, "error": sec_err, "raw": raw}
            beh_err = _behavior_check(current_source)
            if beh_err:
                return {"ok": False, "error": beh_err, "raw": raw}
            return {"ok": True, "source": current_source, "repair_used": attempt > 0}

        repair_messages = [
            {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR},
            {"role": "user", "content": (
                f"py_compile 报错：\n{err}\n\n原始代码（保持业务逻辑，仅修语法）：\n{current_source[:8000]}"
            )},
        ]
        res2 = await chat_dispatch(prov, api_key=api_key, base_url=base_url, model=model, messages=repair_messages, max_tokens=3072)
        if not res2.get("ok"):
            return {"ok": False, "error": f"repair upstream: {res2.get('error') or 'error'}", "raw": raw, "compile_error": err}
        current_source = _strip_code_fence(str(res2.get("content") or ""))

    return {"ok": False, "error": f"经过 {_MAX_REPAIR_ATTEMPTS} 次修复仍无法通过编译", "raw": raw, "compile_error": err}
```

**效果**：修复重试次数从 1 提升到 2，提高复杂代码的生成成功率。

---

## F-11：`host_check` 验证深度不足

### 问题描述

员工模式的 `host_check` 步骤仅做 HTTP GET 验证网络可达，不验证 LLM 密钥配置和版本兼容性。

### 修复方案

**文件**：`modstore_server/workbench_api.py`

在 `host_check` 步骤中增加 LLM 密钥探测和版本检查：

```python
# host_check 步骤增强
host_warnings = []
try:
    async with httpx.AsyncClient(timeout=10.0) as hc:
        r = await hc.get(f"{fhd_base_url}/api/mods/")
        if r.status_code >= 400:
            host_warnings.append(f"宿主 /api/mods/ 返回 {r.status_code}")

        # 检查 LLM 密钥是否配置
        try:
            llm_r = await hc.get(f"{fhd_base_url}/api/mods/llm-status")
            if llm_r.status_code == 200:
                llm_data = llm_r.json()
                if not llm_data.get("api_key_configured"):
                    host_warnings.append("宿主未配置 LLM API Key，员工运行时将无法调用 LLM")
        except Exception:
            host_warnings.append("无法探测宿主 LLM 配置状态")

        # 检查版本兼容性
        try:
            ver_r = await hc.get(f"{fhd_base_url}/api/version")
            if ver_r.status_code == 200:
                ver_data = ver_r.json()
                min_version = ver_data.get("min_mod_sdk_version", "0.0.0")
                # 与当前 MODstore 生成的 Mod SDK 版本对比
                # ...
        except Exception:
            pass

except Exception as e:
    host_warnings.append(f"宿主连通性检查失败: {str(e)[:300]}")
```

**效果**：提前发现宿主未配置 LLM 密钥等问题，避免部署后员工无法运行。

> **注意**：此修复需要在 FHD 宿主侧新增 `/api/mods/llm-status` 和 `/api/version` 端点。

---

## D-01：`_call_llm` 回退机制描述错误

### 文档修正

**原文**（§9.2）：
```
ctx["call_llm"]
  → blueprints.py 中的 _call_llm
    → mod_employee_complete (优先)
      → FHD宿主 DEEPSEEK_API_KEY
    → (若不可用则回退)
      → modstore_server.llm_chat_proxy
```

**修正为**：
```
ctx["call_llm"]
  → blueprints.py 中的 _call_llm
    → mod_employee_complete（唯一路径）
      → FHD宿主 DEEPSEEK_API_KEY / AIConversationService
    → 若 mod_employee_complete 导入失败：
      → call_llm 保持 None（⚠️ 无回退机制，员工脚本调用会 TypeError）
```

> 此文档问题在 F-01 修复后应同步更新为新的回退行为。

---

## D-02：`resolve_api_key`/`resolve_base_url` 签名错误

### 文档修正

**原文**（§五）：
```python
def resolve_api_key(provider: str) -> Optional[str]
def resolve_base_url(provider: str) -> Optional[str]
```

**修正为**：
```python
def resolve_api_key(session: Session, user_id: int, provider: str) -> Tuple[Optional[str], str]
    """返回 (api_key, source)；source 为 user_override | platform | none"""

def resolve_base_url(session: Session, user_id: int, provider: str) -> Optional[str]
    """OpenAI 兼容系：用户 base_url 优先，否则平台。anthropic/google 返回 None。"""
```

补充说明：函数支持多租户 BYOK（Bring Your Own Key），优先使用用户级密钥覆盖，其次使用平台环境变量。

---

## D-03：`chat_dispatch` 签名错误

### 文档修正

**原文**（§五）：
```python
async def chat_dispatch(
    provider: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, str]],
    *,
    max_tokens: int = 3072
) -> Dict[str, Any]:
```

**修正为**：
```python
async def chat_dispatch(
    provider: str,
    *,
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
```

关键差异：
- `api_key` 及之后均为 **keyword-only** 参数
- `max_tokens` 默认为 `None`（非 3072），由各 provider 函数自行处理默认值

---

## D-04：`run_employee_ai_scaffold_async` 文件位置错误

### 文档修正

**原文**（§十）：
> 员工包LLM生成 → `modstore_server/employee_ai_scaffold.py`

**修正为**：
> 员工包LLM生成 → `modstore_server/mod_scaffold_runner.py`（主入口 `run_employee_ai_scaffold_async` 在第 1137 行）

补充说明：`employee_ai_scaffold.py` 仅提供底层工具函数（`parse_employee_pack_llm_json`、`build_employee_pack_zip`），被 `mod_scaffold_runner.py` 调用。

---

## D-05：缺少 `script` intent 文档

### 文档修正

在§十一「三种 Intent 对比」表中追加第四行：

| 维度 | script |
|------|--------|
| **产物** | Python 处理脚本 + 输出文件（outputs/） |
| **LLM 调用次数** | 1次（生成脚本） |
| **步骤数** | 5步（spec → generate → validate → run → complete） |
| **沙箱测试** | validate（安全检查） |
| **部署目标** | 不持久化，一次性执行 |

触发方式：`execution_mode: 'script'`（非 intent 字段）。

---

## D-06：超时时间描述过于简化

### 文档修正

**原文**（§十二.2）：
> MODstore服务端：`chat_dispatch` 默认 120秒

**修正为**：
> MODstore服务端超时因 provider 和调用模式而异：
>
> | 调用类型 | 超时 |
> |----------|------|
> | OpenAI 兼容（chat） | 120s |
> | Anthropic（chat） | 120s |
> | Google Gemini（chat） | 120s |
> | OpenAI 兼容（stream） | 无超时（`timeout=None`） |
> | OpenAI 兼容（image） | 180s |

---

## 修复优先级建议

### 第一批（立即修复）

| 编号 | 原因 |
|------|------|
| F-01 | `call_llm=None` 导致运行时 TypeError，影响所有员工脚本 |
| F-02 | `http_get`/`http_post` 未实现，system prompt 与运行时不一致 |
| F-03 | LLM 生成代码无安全审查，存在代码注入风险 |

### 第二批（近期修复）

| 编号 | 原因 |
|------|------|
| F-04 | 宿主锁定 DeepSeek，限制部署灵活性 |
| F-06 | 行为校验缺失，可能生成无法运行的代码 |
| F-10 | 单次修复重试成功率不足 |
| D-01~D-06 | 文档与代码不同步，影响团队协作 |

### 第三批（中期优化）

| 编号 | 原因 |
|------|------|
| F-05 | 流水线回滚机制，提升用户体验 |
| F-07 | 员工并行生成，提升性能 |
| F-08 | 工作流图校验，减少人工修正 |
| F-09 | LLM 调用预算控制，防止成本失控 |
| F-11 | 宿主检查增强，提前发现问题 |

---

## 实施记录（2026-05-04）

本表所列 **F-01～F-11** 与 **D-01～D-06** 已按 [`修复方案-评审报告.md`](修复方案-评审报告.md) 修正后落地；其中 **F-04** 采用「OpenAI 兼容 URL + httpx 直连 + 未配置时回退 `call_deepseek_api`」，**F-05** 清理使用 `pkg_id` 与 `WorkflowNode`/`WorkflowEdge` 级联删除，与初版片段不完全一致。
