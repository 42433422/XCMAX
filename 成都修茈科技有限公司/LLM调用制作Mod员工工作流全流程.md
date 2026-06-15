# LLM调用制作Mod、员工和工作流全流程

> 文档生成时间：2026-05-04  
> 基于代码：`e:\成都修茈科技有限公司\MODstore_deploy` 与 `e:\FHD`

---

## 一、整体架构概览

整个系统分为三个核心层次：

| 层级 | 位置 | 职责 |
|------|------|------|
| **前端工作台** | `market/src/views/WorkbenchHomeView.vue` | 用户交互、需求规划、进度展示 |
| **MODstore编排服务** | `modstore_server/workbench_api.py` | 异步编排、LLM调度、产物落盘 |
| **FHD宿主** | `FHD/app/mod_sdk/` | 运行时加载、员工执行、LLM窄入口 |

---

## 二、「做Mod」完整流程

### 阶段1：需求规划（前端）

1. 用户在`WorkbenchHomeView.vue`选择**「做Mod」**档位
2. 输入自然语言需求 brief
3. 与规划助手多轮对话澄清需求
4. 生成执行清单(`execution_checklist`)
5. 确认清单后点击**「开始生成Mod」**

### 阶段2：后端编排

前端调用：
```
POST /api/workbench/sessions
Body: {
  intent: 'mod',
  brief: '需求描述',
  planning_messages: [...],
  execution_checklist: [...],
  generate_full_suite: true  // 默认全套生成
}
```

返回：`{ session_id: 'xxx', status: 'running' }`

前端轮询：
```
GET /api/workbench/sessions/{session_id}
```

---

## 三、服务端12步编排流程

**入口函数**：`workbench_api.py` → `_run_pipeline()`

| 步骤 | ID | 用户可见标签 | 含义与产物 | 核心函数 |
|------|-----|-------------|-----------|----------|
| 1 | `spec` | 理解需求 | 初始化会话，校验用户 | - |
| 2 | `manifest` | 生成蓝图与JSON | **LLM生成结构化Mod蓝图** | `generate_mod_suite_blueprint_async` |
| 3 | `repo` | 新建Mod仓库 | 落盘Mod目录（含backend/、manifest等） | `import_mod_suite_repository` |
| 4 | `industry` | 生成行业卡片 | 写入行业配置与侧栏菜单 | `write_mod_suite_industry_card` |
| 5 | `employees` | 创建员工骨架 | 瞬时步骤，骨架已在repo阶段写入 | - |
| 6 | `employee_impls` | 生成员工脚本 | **LLM为每员工生成Python实现** | `generate_mod_employee_impls_async` |
| 7 | `workflows` | 生成员工Skill组 | 为每员工创建画布工作流并生成图 | `create_mod_suite_workflows_async` |
| 8 | `register_packs` | 登记员工包并修复图 | 修复画布employee节点对齐+五维审核登记 | `register_mod_employee_packs_async` |
| 9 | `api` | 生成/绑定API节点 | 汇总OpenAPI节点 | - |
| 10 | `workflow_sandbox` | 工作流沙箱测试 | Mock执行员工工作流 | `run_mod_suite_workflow_sandboxes` |
| 11 | `mod_sandbox` | Mod沙箱测试 | 校验manifest、蓝图与路由骨架 | `run_mod_suite_mod_sandbox` |
| 12 | `complete` | 完成 | 会话状态置为done | - |

---

## 四、LLM调用详解

### 1. Mod蓝图生成（步骤2：manifest）

**文件**：[`modstore_server/mod_ai_scaffold.py`](file:///e:/成都修茈科技有限公司/MODstore_deploy/modstore_server/mod_ai_scaffold.py)

#### System Prompt

```python
SYSTEM_PROMPT_SUITE = """你是 XCAGI Mod 清单生成器。用户会用自然语言描述想要的扩展 Mod。
你必须只输出一个 JSON 对象（不要 markdown 围栏、不要解释文字），字段如下：
- id: 字符串，小写英文/数字/点/下划线/连字符，以字母或数字开头，建议 2–48 字符
- name: 简短中文或英文显示名
- version: 语义化版本，默认 "1.0.0"
- description: 一句话介绍
- workflow_employees: 可选数组；每项为对象，含 id、label、panel_title、panel_summary

此外请输出 Mod 蓝图 JSON：包含 manifest（对象）、employees（数组）、blueprint（对象）。"""
```

#### LLM输出格式

```json
{
  "manifest": {
    "id": "demo-helper",
    "name": "演示助手",
    "version": "1.0.0",
    "description": "示例Mod",
    "workflow_employees": [
      {"id": "helper-1", "label": "助手", "panel_title": "助手", "panel_summary": "占位说明"}
    ]
  },
  "employees": [...],
  "blueprint": {...}
}
```

#### 解析流程

```python
await chat_dispatch(
    provider,
    api_key=api_key,
    base_url=base_url,
    model=model,
    messages=messages,
    max_tokens=...,
)
  → parse_llm_mod_suite_json(content)
  → validate_manifest_dict(manifest)
  → 返回 {"ok": True, "parsed": {...}}
```

---

### 2. 员工脚本生成（步骤6：employee_impls）

**文件**：[`modstore_server/mod_employee_impl_scaffold.py`](file:///e:/成都修茈科技有限公司/MODstore_deploy/modstore_server/mod_employee_impl_scaffold.py)

#### 关键特性

- 对**每名员工单独调用LLM一次**
- 生成后立刻 `py_compile` 校验
- 语法失败则**一次修复重试**

#### System Prompt（核心约束）

```python
SYSTEM_PROMPT_EMPLOYEE_IMPL = """你是 XCAGI 工作台 Mod 员工实现代码生成器。

必须严格遵守：
1. 文件顶部允许 from __future__ import annotations、标准库 import、httpx/requests
2. FHD 宿主 import 边界：仅允许 from app.mod_sdk.<子模块> import ...
   禁止 from app.routes、from app.application、from app.services 等
3. 禁止：相对 import、import *、访问文件系统外部路径、硬编码 API key
4. 必须实现：
   async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]
   
   ctx 包含：
   - ctx["mod_id"]（str）
   - ctx["employee_id"]（str）
   - ctx["logger"]（logging.Logger）
   - ctx["call_llm"]（async callable）
   - ctx["http_get"]（async callable）
   - ctx["http_post"]（async callable）
5. 代码风格：类型标注完整；最多 ~200 行；注释用简体中文
6. 输出内容必须能通过 py_compile 校验"""
```

#### 单员工生成流程

```python
async def _generate_one_employee_py(...) -> Dict[str, Any]:
    # 1. 拼装员工画像消息
    user_msg = "\n".join(_employee_brief_lines(emp, ...))
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL},
        {"role": "user", "content": user_msg},
    ]
    
    # 2. 首次LLM调用
    res = await chat_dispatch(
        prov,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=3072,
    )
    raw = _strip_code_fence(res["content"])
    
    # 3. 语法校验
    err = _compile_check(raw)
    if not err:
        return {"ok": True, "source": raw}
    
    # 4. 失败则修复重试
    repair_messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EMPLOYEE_IMPL_REPAIR},
        {"role": "user", "content": f"py_compile报错：\n{err}\n\n原始代码：\n{raw[:8000]}"},
    ]
    res2 = await chat_dispatch(...)
    return {"ok": True/False, "source": raw}
```

#### 产物落盘

```
{mod_dir}/backend/employees/
  ├── __init__.py
  ├── helper_1.py      # 员工1实现
  ├── data_analyzer.py  # 员工2实现
  └── ...
```

---

### 3. 工作流生成（步骤7：workflows）

**文件**：[`modstore_server/mod_scaffold_runner.py`](file:///e:/成都修茈科技有限公司/MODstore_deploy/modstore_server/mod_scaffold_runner.py)

#### 流程

```python
async def create_mod_suite_workflows_async(...):
    for emp in employees:
        # 1. 创建Workflow记录
        wf = Workflow(
            user_id=user.id,
            name=f"{emp['label']}工作流",
            description=emp['panel_summary'],
            is_active=True,
        )
        db.add(wf)
        db.commit()
        
        # 2. LLM生成画布节点和边
        nl = await apply_nl_workflow_graph(
            db, user, workflow_id=wf.id,
            brief=brief, provider=prov, model=mdl
        )
        
        # 3. 记录结果
        workflow_results.append({
            "workflow_id": wf.id,
            "ok": nl["ok"],
            "graph": nl.get("graph"),
        })
```

---

## 五、LLM统一出口

### MODstore服务端：`llm_chat_proxy.py`

**文件**：[`modstore_server/llm_chat_proxy.py`](file:///e:/成都修茈科技有限公司/MODstore_deploy/modstore_server/llm_chat_proxy.py)

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
    """
    统一聊天代理：支持 OpenAI兼容 / Anthropic / Google Gemini

    返回: {"ok": bool, "content": str, "error": str, "usage": {...}}
    - api_key 及之后参数均为 keyword-only
    - max_tokens 默认 None，由各 provider 分支自行默认
    """
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        return await chat_openai_compatible(base_url, api_key, model, messages,
                                           max_tokens=max_tokens)
    # ... 其他provider处理
```

#### 凭证解析：`llm_key_resolver.py`

```python
def resolve_api_key(session: Session, user_id: int, provider: str) -> Tuple[Optional[str], str]:
    """返回 (api_key, source)；source 为 user_override | platform | none"""

def resolve_base_url(session: Session, user_id: int, provider: str) -> Optional[str]:
    """OpenAI 兼容系：用户 base_url 优先，否则平台。anthropic/google 返回 None。"""
```

---

## 六、FHD宿主侧LLM调用

### Mod员工运行时LLM入口

**文件**：[`FHD/app/mod_sdk/mod_employee_llm.py`](file:///e:/FHD/app/mod_sdk/mod_employee_llm.py)

```python
async def mod_employee_complete(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: Any = None,
) -> dict[str, Any]:
    """
    为员工 run(payload, ctx) 提供单次补全
    返回形状与 MODstore chat_dispatch 对齐:
    {"ok": bool, "content": str, "error": str}
    
    实现上委托 AIConversationService.call_deepseek_api
    使用宿主已配置的 DEEPSEEK_API_KEY
    """
    svc = get_ai_conversation_service()
    if not getattr(svc, "api_key", None):
        return {"ok": False, "content": "", "error": "宿主未配置 DEEPSEEK_API_KEY"}
    
    raw = await svc.call_deepseek_api(messages, temperature=temperature, 
                                      max_tokens=max_tokens)
    # 解析返回...
    return {"ok": True, "content": content, "error": ""}
```

### 员工脚本调用约定

```python
# 员工 run() 函数内：
async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    # 优先使用 ctx["call_llm"]
    result = await ctx["call_llm"](
        messages=[{"role": "system", "content": "..."}, 
                  {"role": "user", "content": "..."}],
        max_tokens=1024,
        temperature=0.2
    )
    
    if result["ok"]:
        # 处理LLM返回内容
        content = result["content"]
    else:
        # 处理错误
        error = result["error"]
```

**调用链路**：
```
ctx["call_llm"]
  → blueprints.py 中的 _call_llm
    → mod_employee_complete（宿主侧唯一路径；OpenAI 兼容 chat/completions）
      → 默认：AIConversationService.call_deepseek_api + DEEPSEEK_API_KEY
      → 可选：XCAGI_LLM_PROVIDER + {PROVIDER}_API_KEY + {PROVIDER}_BASE_URL（或内置默认 URL）时 httpx 直连
    → 若 mod_employee_complete 导入失败：call_llm 注入为降级函数，返回明确错误 dict（非 None）
```

---

## 七、「做员工」独立流程

**入口**：`intent: 'employee'`

### 编排步骤

| 步骤 | 说明 |
|------|------|
| `spec` | 理解需求 |
| `generate` | **LLM生成employee_pack**（manifest + zip） |
| `validate` | 服务端校验manifest |
| `workflow` | (可选)创建画布工作流 |
| `workflow_sandbox` | 工作流沙箱测试 |
| `mod_sandbox` | 包体校验（Python编译） |
| `host_check` | 宿主连通性探测 |
| `complete` | 完成 |

### 模式选择

- `pack_only`：仅生成员工包zip
- `pack_plus_workflow`：额外创建画布工作流并写回manifest

### 产物

```
employee_pack.zip
  ├── manifest.json
  ├── backend/
  │   ├── blueprints.py
  │   └── employees/
  │       └── <stem>.py
  ├── employee_config_v2
  └── xcagi_host_profile (可选)
```

---

## 八、「做工作流/Skill组」流程

**入口**：`intent: 'skill'`（旧称workflow）

### 流程

1. 创建 `Workflow(kind="skill_group")` 记录
2. 若 `generate_workflow_graph=true`：
   - 调用 `apply_nl_workflow_graph`（**LLM生成节点和边**）
3. 沙箱校验：`run_workflow_sandbox(mock_employees=True)`

### 编排步骤

| 步骤 | 说明 |
|------|------|
| `spec` | 理解需求 |
| `generate` | 创建Skill组 + (可选)LLM生成画布图 |
| `validate` | 服务端校验 |
| `complete` | 完成 |

---

## 九、关键数据流图

```mermaid
flowchart TD
  A[用户输入brief] --> B[前端规划对话 WorkbenchHomeView.vue]
  B --> C[POST /api/workbench/sessions]
  C --> D[workbench_api._run_pipeline]
  
  D --> E{intent?}
  
  E -->|mod| F1[LLM → mod_ai_scaffold → manifest.json]
  E -->|mod| F2[模板填充 → import_mod_suite_repository → 落盘]
  E -->|mod| F3[LLM × N员工 → mod_employee_impl_scaffold → backend/employees/*.py]
  E -->|mod| F4[LLM × N工作流 → create_mod_suite_workflows_async → DB]
  
  E -->|employee| G1[LLM → employee_ai_scaffold → employee_pack.zip]
  E -->|employee| G2[可选: 创建工作流]
  
  E -->|skill| H1[创建Workflow kind=skill_group]
  E -->|skill| H2[可选: LLM生成节点和边]
  
  F4 --> I[前端轮询 GET /api/workbench/sessions/{id}]
  G2 --> I
  H2 --> I
  
  I --> J[跳转 ModAuthoringView.vue 编辑]
  J --> K[部署到FHD: XCAGI_MODS_ROOT/mods/<id>/]
  K --> L[FHD ModManager.load_modroutes]
  L --> M[员工运行时: ctx.call_llm → mod_employee_complete → 宿主 LLM 配置或 XCAGI_LLM_PROVIDER 直连]
```

---

## 十、关键源码位置速查

| 内容 | 文件路径 |
|------|----------|
| 前端UI/编排入口 | `market/src/views/WorkbenchHomeView.vue` |
| Mod制作页 | `market/src/views/ModAuthoringView.vue` |
| 后端编排核心 | `modstore_server/workbench_api.py` |
| Mod蓝图LLM生成 | `modstore_server/mod_ai_scaffold.py` |
| 员工脚本LLM生成 | `modstore_server/mod_employee_impl_scaffold.py` |
| 员工包LLM生成（主入口） | `modstore_server/mod_scaffold_runner.py`（`run_employee_ai_scaffold_async`） |
| 员工包 zip 工具 | `modstore_server/employee_ai_scaffold.py`（`parse_employee_pack_llm_json`、`build_employee_pack_zip`） |
| 工作流创建 | `modstore_server/mod_scaffold_runner.py` |
| LLM统一出口 | `modstore_server/llm_chat_proxy.py` |
| 凭证解析 | `modstore_server/llm_key_resolver.py` |
| FHD宿主SDK | `FHD/app/mod_sdk/__init__.py` |
| FHD员工LLM入口 | `FHD/app/mod_sdk/mod_employee_llm.py` |
| 流程文档 | `docs/workbench-make-mod-workflow.md` |
| 员工实现流程文档 | `docs/workbench-employee-impl-flow.md` |

---

## 十一、Intent 与 execution_mode 对比

| 维度 | mod | employee | skill | script（execution_mode） |
|------|-----|----------|-------|-------------------------|
| **产物** | Mod仓库（含manifest+员工脚本+工作流） | employee_pack zip | Workflow记录（Skill组） | Python 处理脚本 + outputs/ |
| **LLM调用次数** | 1次蓝图 + N次员工 + N次工作流 | 1次员工包 + (可选)1次工作流图 | 0或1次（生成画布图） | 1次（生成脚本） |
| **步骤数** | 12步 | 8步 | 4步 | 5步（spec → generate → validate → run → complete） |
| **沙箱测试** | workflow_sandbox + mod_sandbox | workflow_sandbox + mod_sandbox | validate_only沙箱 | validate（安全检查） |
| **部署目标** | XCAGI_MODS_ROOT/mods/<id>/ | _employees/ | 数据库Workflow表 | 不持久化，一次性执行 |

> **script**：通过请求体 `execution_mode: 'script'` 触发（不是 `intent` 字段）。

---

## 十二、注意事项与最佳实践

### 1. 员工脚本LLM生成约束

- 仅允许 `from app.mod_sdk.<子模块> import ...`
- 禁止硬编码API Key、相对import、访问外部文件系统
- 必须实现 `async def run(payload, ctx) -> Dict[str, Any]`
- 生成后强制 `py_compile` 校验，失败则一次修复重试

### 2. LLM调用超时控制

MODstore 服务端超时因 provider 与调用模式而异（见 `llm_chat_proxy.py`）：

| 调用类型 | 超时 |
|----------|------|
| OpenAI 兼容（chat） | 120s |
| Anthropic（chat） | 120s |
| Google Gemini（chat） | 120s |
| OpenAI 兼容（stream） | 无超时（`timeout=None`） |
| OpenAI 兼容（image） | 180s |

FHD 宿主：员工侧直连或 `call_deepseek_api` 使用各自 httpx 超时配置。

### 3. 凭证管理

- MODstore：环境变量/配置文件按provider查密钥
- FHD：宿主统一配置 `DEEPSEEK_API_KEY`
- 员工脚本：禁止硬编码，必须从 `ctx.get("secrets")` 读取

### 4. 产物校验

- 语法：`py_compile`
- manifest：`validate_manifest_dict`
- 沙箱：`run_workflow_sandbox` / `run_mod_suite_mod_sandbox`

---

*文档版本：与当前代码库 `workbench_api.py` / `mod_ai_scaffold.py` / `mod_employee_impl_scaffold.py` / `mod_employee_llm.py` 对齐*
