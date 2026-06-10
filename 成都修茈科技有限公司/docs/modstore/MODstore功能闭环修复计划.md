# MODstore 功能逻辑闭环修复计划

> 本文档基于对项目代码的全面审计，梳理从「用户制作 AI 员工 → 上架 → 购买 → 真实执行」全链路的缺口，并提供可执行的修复方案。

---

## 一、项目现状速览


| 模块        | 完成度  | 核心问题                             |
| --------- | ---- | -------------------------------- |
| 支付系统      | ~85% | 退款/售后流程不完整，Java 支付服务未接入主服务       |
| 用户系统      | ~90% | 缺少密码找回、用户资料编辑                    |
| AI 员工制作向导 | ~95% | 前端 10 步向导完整，但**后端执行引擎是模拟的**      |
| 工作流编辑器    | ~90% | 画布/节点/边完整，但**员工节点调用的是 mock 执行器** |
| 商店/目录     | ~80% | 浏览/购买/上架流程存在，但真实执行后无产出           |
| 工作台       | ~75% | AI 编排会话存在，但生成的工作流/员工无法真实运行       |
| 部署运维      | ~60% | 基础脚本存在，缺少监控/告警/自动备份              |
| 消息通知      | ~10% | 几乎空白                             |
| 工作流触发器    | ~20% | 数据库表存在，但无调度器实现                   |


**最大阻断点：用户能「制作」和「购买」AI 员工，但员工无法真正干活（Cognition 未调用 LLM、Actions 未调用真实工具）。**

---

## 二、修复优先级总览

```
P0（阻断商业闭环）
  ├── 2.1 实现真实 Cognition（接入 LLM）
  ├── 2.2 实现真实 Actions（工具调用）
  ├── 2.3 实现真实 Perception（输入解析）
  └── 2.4 工作流员工节点真实执行

P1（影响核心体验）
  ├── 3.1 工作流触发器（定时/Webhook/事件）
  ├── 3.2 消息通知系统
  ├── 3.3 配额检查中间件全面接入
  └── 3.4 退款/售后流程

P2（运营与优化）
  ├── 4.1 使用统计面板
  ├── 4.2 部署监控与告警
  └── 4.3 工作台首页改造
```

---

## 三、P0 修复：AI 员工真实执行引擎

### 3.1 现状分析

当前 `employee_executor.py` 的执行管道：

```python
# _perception  →  直接返回 input_data，无解析
# _memory_load →  返回空 session，无记忆
# _cognition    →  直接返回 system_prompt 字符串，**未调用 LLM**
# _actions      →  返回 echo，**未调用任何工具**
```

### 3.2 修复目标

让 `execute_employee_task` 成为真实执行管道：

```
Input → Perception（解析/理解）→ Memory（加载上下文）→ Cognition（LLM 推理）→ Actions（工具执行）→ Output
```

### 3.3 具体修复步骤

#### 步骤 1：改造 `_cognition` —— 接入 LLM

**文件**：`modstore_server/employee_executor.py`

**修改内容**：

```python
import asyncio
from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import resolve_api_key, resolve_base_url, OAI_COMPAT_OPENAI_STYLE_PROVIDERS

async def _cognition_real(
    config: Dict[str, Any],
    perceived: Dict[str, Any],
    memory: Dict[str, Any],
    session,      # SQLAlchemy Session
    user_id: int, # 当前用户 ID，用于解析 API Key
) -> Dict[str, Any]:
    """
    真实 Cognition：根据 cognition.agent 配置调用 LLM。
    """
    agent = (config.get("cognition") or {}).get("agent") or {}
    system_prompt = agent.get("system_prompt", "你是智能员工助手")
    
    # 构建 messages
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    
    # 加载记忆上下文
    mem_ctx = ""
    if memory and memory.get("session"):
        mem_ctx = f"\n[会话上下文]\n{json.dumps(memory['session'], ensure_ascii=False)}"
    
    # 构建用户输入
    user_input = json.dumps(perceived.get("normalized_input", {}), ensure_ascii=False)
    if mem_ctx:
        user_input = f"{user_input}{mem_ctx}"
    
    messages.append({"role": "user", "content": user_input})
    
    # 解析模型配置
    model_cfg = agent.get("model") or {}
    provider = model_cfg.get("provider", "deepseek")
    model_name = model_cfg.get("model_name", "deepseek-chat")
    max_tokens = model_cfg.get("max_tokens", 4000)
    
    # 解析 API Key
    api_key, source = resolve_api_key(session, user_id, provider)
    if not api_key:
        return {
            "reasoning": "",
            "error": f"未配置 {provider} 的 API Key",
            "input": perceived.get("normalized_input", {}),
            "memory": memory,
        }
    
    base_url = None
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        base_url = resolve_base_url(session, user_id, provider)
    
    # 调用 LLM
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        messages=messages,
        max_tokens=max_tokens,
    )
    
    if not result.get("ok"):
        return {
            "reasoning": "",
            "error": result.get("error", "LLM 调用失败"),
            "input": perceived.get("normalized_input", {}),
            "memory": memory,
        }
    
    return {
        "reasoning": result.get("content", ""),
        "input": perceived.get("normalized_input", {}),
        "memory": memory,
        "llm_raw": result.get("raw"),  # 保留原始响应供调试
    }
```

**同步包装**（因为 `execute_employee_task` 是同步的）：

```python
def _cognition_sync(config, perceived, memory, session, user_id):
    return asyncio.run(_cognition_real(config, perceived, memory, session, user_id))
```

#### 步骤 2：改造 `_actions` —— 实现工具调用

**文件**：`modstore_server/employee_executor.py`

**修改内容**：

```python
def _actions_real(
    config: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
) -> Dict[str, Any]:
    """
    真实 Actions：根据配置调用对应工具。
    当前支持：echo, webhook, http_request, wechat_notify（占位）, data_sync
    """
    actions_cfg = config.get("actions") or {}
    handlers = actions_cfg.get("handlers", ["echo"])
    outputs = []
    
    for handler in handlers:
        if handler == "echo":
            outputs.append({
                "handler": "echo",
                "output": reasoning.get("reasoning", ""),
            })
        
        elif handler == "http_request":
            http_cfg = actions_cfg.get("http_request") or {}
            url = http_cfg.get("url", "")
            method = http_cfg.get("method", "POST")
            headers = http_cfg.get("headers", {})
            body_template = http_cfg.get("body", "")
            
            # 简单模板替换
            body = body_template.replace("{{reasoning}}", reasoning.get("reasoning", ""))
            body = body.replace("{{task}}", task)
            
            import httpx
            try:
                resp = httpx.request(method, url, headers=headers, content=body, timeout=30)
                outputs.append({
                    "handler": "http_request",
                    "status_code": resp.status_code,
                    "response": resp.text[:2000],
                })
            except Exception as e:
                outputs.append({
                    "handler": "http_request",
                    "error": str(e),
                })
        
        elif handler == "webhook":
            webhook_cfg = actions_cfg.get("webhook") or {}
            url = webhook_cfg.get("url", "")
            if url:
                import httpx
                try:
                    payload = {
                        "employee_id": employee_id,
                        "task": task,
                        "result": reasoning.get("reasoning", ""),
                    }
                    resp = httpx.post(url, json=payload, timeout=30)
                    outputs.append({
                        "handler": "webhook",
                        "status_code": resp.status_code,
                    })
                except Exception as e:
                    outputs.append({
                        "handler": "webhook",
                        "error": str(e),
                    })
        
        elif handler == "data_sync":
            # 数据同步：将结果写入数据库或文件
            sync_cfg = actions_cfg.get("data_sync") or {}
            target = sync_cfg.get("target", "log")
            if target == "log":
                logger.info("[data_sync] employee=%s task=%s result=%s", 
                           employee_id, task, reasoning.get("reasoning", "")[:500])
                outputs.append({"handler": "data_sync", "target": "log", "status": "ok"})
        
        elif handler == "wechat_notify":
            # 微信通知：需要接入企业微信/微信 API（当前占位）
            outputs.append({
                "handler": "wechat_notify",
                "status": "not_implemented",
                "message": "微信通知需要配置企业微信 API",
            })
        
        else:
            outputs.append({"handler": handler, "error": "未知的 handler"})
    
    return {
        "task": task,
        "handlers": handlers,
        "outputs": outputs,
        "summary": f"executed {len(outputs)} handlers",
    }
```

#### 步骤 3：改造 `_perception` —— 输入解析

```python
def _perception_real(config: Dict[str, Any], input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    真实 Perception：根据配置解析输入。
    支持：text, json, csv, excel（占位）, image（占位）
    """
    p_cfg = config.get("perception") or {}
    p_type = p_cfg.get("type", "text")
    
    if p_type == "text":
        return {"normalized_input": input_data, "type": "text"}
    
    elif p_type == "json":
        if isinstance(input_data, dict):
            return {"normalized_input": input_data, "type": "json"}
        try:
            parsed = json.loads(input_data) if isinstance(input_data, str) else input_data
            return {"normalized_input": parsed, "type": "json"}
        except Exception:
            return {"normalized_input": input_data, "type": "json", "parse_error": True}
    
    elif p_type == "csv":
        import csv
        import io
        raw = input_data.get("content", "") if isinstance(input_data, dict) else str(input_data)
        try:
            reader = csv.DictReader(io.StringIO(raw))
            rows = list(reader)
            return {"normalized_input": {"rows": rows}, "type": "csv", "row_count": len(rows)}
        except Exception as e:
            return {"normalized_input": input_data, "type": "csv", "parse_error": str(e)}
    
    elif p_type == "excel":
        # 需要 openpyxl，当前占位
        return {
            "normalized_input": input_data,
            "type": "excel",
            "note": "Excel 解析需要安装 openpyxl 并配置",
        }
    
    elif p_type == "image":
        return {
            "normalized_input": input_data,
            "type": "image",
            "note": "图片解析需要接入 OCR 或 vision model",
        }
    
    return {"normalized_input": input_data, "type": p_type}
```

#### 步骤 4：改造 `_memory_load` —— 记忆加载

```python
def _memory_real(config: Dict[str, Any], ctx: Dict[str, Any], session, user_id: int) -> Dict[str, Any]:
    """
    真实 Memory：加载短期记忆（最近执行记录）和长期记忆（知识库）。
    """
    mem_cfg = config.get("memory") or {}
    result = {"session": {"employee_id": ctx["employee_id"]}, "long_term": None}
    
    # 短期记忆：最近 5 条执行记录
    if mem_cfg.get("short_term", {}).get("enabled", True):
        from modstore_server.models import EmployeeExecutionMetric
        recent = (
            session.query(EmployeeExecutionMetric)
            .filter(EmployeeExecutionMetric.employee_id == ctx["employee_id"])
            .order_by(EmployeeExecutionMetric.id.desc())
            .limit(5)
            .all()
        )
        result["session"]["recent_tasks"] = [
            {"task": r.task, "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in recent
        ]
    
    # 长期记忆：知识库（当前占位）
    if mem_cfg.get("long_term", {}).get("enabled", False):
        result["long_term"] = {
            "enabled": True,
            "note": "知识库需要接入向量数据库（如 Chroma/Qdrant）",
        }
    
    return result
```

#### 步骤 5：整合 `execute_employee_task`

```python
def execute_employee_task(
    employee_id: str,
    task: str,
    input_data: Dict[str, Any] = None,
    user_id: int = 0,  # 新增参数，用于解析 LLM API Key
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    payload = input_data or {}
    sf = get_session_factory()
    with sf() as session:
        try:
            pack = load_employee_pack(session, employee_id)
            config = parse_employee_config_v2(pack.get("manifest") or {})
            ctx = build_employee_context(employee_id, payload)
            
            # 真实执行管道
            perceived = _perception_real(config.get("perception", {}), payload)
            memory = _memory_real(config.get("memory", {}), ctx, session, user_id)
            reasoning = _cognition_sync(config, perceived, memory, session, user_id)
            result = _actions_real(config.get("actions", {}), reasoning, task, employee_id)
            
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            llm_tokens = _extract_token_count(reasoning)  # 从 LLM 响应中提取
            
            session.add(
                EmployeeExecutionMetric(
                    user_id=user_id,
                    employee_id=employee_id,
                    task=task,
                    status="success",
                    duration_ms=duration_ms,
                    llm_tokens=llm_tokens,
                )
            )
            session.commit()
            
            return {
                "employee_id": employee_id,
                "pack": {"id": pack["pack_id"], "version": pack["version"]},
                "duration_ms": duration_ms,
                "result": result,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "llm_tokens": llm_tokens,
            }
        except Exception as e:
            duration_ms = round((time.perf_counter() - t0) * 1000, 3)
            session.add(
                EmployeeExecutionMetric(
                    user_id=user_id,
                    employee_id=employee_id,
                    task=task,
                    status="failed",
                    duration_ms=duration_ms,
                    llm_tokens=0,
                    error=str(e),
                )
            )
            session.commit()
            raise

def _extract_token_count(reasoning: Dict[str, Any]) -> int:
    """从 LLM 原始响应中提取 token 用量。"""
    raw = reasoning.get("llm_raw") or {}
    usage = raw.get("usage") or {}
    return usage.get("total_tokens", 0) or usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
```

#### 步骤 6：修改 `workflow_engine.py` 传递 user_id

**文件**：`modstore_server/workflow_engine.py`

在 `_execute_employee_node` 中，需要获取当前用户 ID 并传递给 `execute_employee_task`：

```python
def _execute_employee_node(self, node, data, config):
    # ... 现有代码 ...
    # 需要从 session 或上下文获取 user_id
    # 当前 workflow_engine 没有 user_id 上下文，需要修改 execute_workflow 和 run_sandbox 的签名
    pass
```

**修改方案**：

```python
# 在 WorkflowEngine 中添加 user_id 上下文
class WorkflowEngine:
    def __init__(self, user_id: int = 0):
        self.user_id = user_id
        self.executors = {...}
    
    def _execute_employee_node(self, node, data, config):
        # ...
        result = execute_employee_task(employee_id, task, input_data, user_id=self.user_id)
        # ...
```

在 `workflow_api.py` 中调用时传入 user_id：

```python
# execute_workflow 接口
output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)

# sandbox_run_workflow 接口
report = run_workflow_sandbox(
    workflow_id,
    body.input_data,
    mock_employees=body.mock_employees,
    validate_only=body.validate_only,
    user_id=user.id,  # 新增
)
```

---

## 四、P1 修复：核心体验完善

### 4.1 工作流触发器调度器

**现状**：`WorkflowTrigger` 表存在，但无调度器实现。

**修复方案**：

1. **新增文件**：`modstore_server/workflow_scheduler.py`

```python
"""工作流触发器调度器：支持 cron、webhook、event 触发。"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from modstore_server.models import WorkflowTrigger, get_session_factory
from modstore_server.workflow_engine import execute_workflow

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None

async def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    await _load_triggers()
    logger.info("工作流调度器已启动")

def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None

async def _load_triggers():
    """从数据库加载所有激活的 cron 触发器。"""
    sf = get_session_factory()
    with sf() as session:
        triggers = session.query(WorkflowTrigger).filter(
            WorkflowTrigger.trigger_type == "cron",
            WorkflowTrigger.is_active == True,
        ).all()
        for t in triggers:
            await _register_cron_trigger(t)

async def _register_cron_trigger(trigger: WorkflowTrigger):
    """注册 cron 触发器到 APScheduler。"""
    config = json.loads(trigger.config_json or "{}")
    cron_expr = config.get("cron", "0 0 * * *")  # 默认每天 0 点
    
    def job_wrapper():
        try:
            execute_workflow(trigger.workflow_id, {}, user_id=trigger.user_id)
        except Exception as e:
            logger.error("定时触发执行失败: workflow=%s error=%s", trigger.workflow_id, e)
    
    _scheduler.add_job(
        job_wrapper,
        CronTrigger.from_crontab(cron_expr),
        id=f"wf_trigger_{trigger.id}",
        replace_existing=True,
    )
    logger.info("已注册 cron 触发器: workflow=%s cron=%s", trigger.workflow_id, cron_expr)

async def trigger_webhook(workflow_id: int, payload: Dict[str, Any], user_id: int):
    """Webhook 触发：直接执行工作流。"""
    try:
        result = execute_workflow(workflow_id, payload, user_id=user_id)
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error("Webhook 触发失败: workflow=%s error=%s", workflow_id, e)
        return {"ok": False, "error": str(e)}
```

1. **在 `app.py` 启动时初始化调度器**：

```python
@app.on_event("startup")
async def startup():
    from modstore_server.workflow_scheduler import start_scheduler
    await start_scheduler()

@app.on_event("shutdown")
async def shutdown():
    from modstore_server.workflow_scheduler import stop_scheduler
    stop_scheduler()
```

1. **新增 Webhook 触发 API**：

```python
# workflow_api.py
@router.post("/{workflow_id}/webhook-trigger", summary="Webhook 触发工作流")
async def webhook_trigger_workflow(
    workflow_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    """通过 webhook 触发工作流执行（需要配置触发器）。"""
    from modstore_server.workflow_scheduler import trigger_webhook
    
    # 验证工作流所有权
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.user_id == user.id,
    ).first()
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    
    # 检查是否有 webhook 类型的触发器
    trigger = db.query(WorkflowTrigger).filter(
        WorkflowTrigger.workflow_id == workflow_id,
        WorkflowTrigger.trigger_type == "webhook",
        WorkflowTrigger.is_active == True,
    ).first()
    if not trigger:
        raise HTTPException(400, "该工作流未配置 webhook 触发器")
    
    result = await trigger_webhook(workflow_id, payload, user.id)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error"))
    return result
```

1. **依赖安装**：

```bash
pip install apscheduler
```

### 4.2 消息通知系统

**新增文件**：`modstore_server/notification_service.py`

```python
"""消息通知服务：支持站内信、邮件（占位）、Webhook。"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import Notification, get_session_factory

logger = logging.getLogger(__name__)

class NotificationType(str, Enum):
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    EMPLOYEE_EXECUTION_DONE = "employee_execution_done"
    QUOTA_WARNING = "quota_warning"
    SYSTEM = "system"

def create_notification(
    user_id: int,
    notification_type: NotificationType,
    title: str,
    content: str,
    data: Dict[str, Any] = None,
    db: Session = None,
) -> Notification:
    """创建通知记录。"""
    should_close = False
    if db is None:
        sf = get_session_factory()
        db = sf()
        should_close = True
    
    try:
        notif = Notification(
            user_id=user_id,
            type=notification_type.value,
            title=title,
            content=content,
            data_json=json.dumps(data or {}, ensure_ascii=False),
            is_read=False,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif
    finally:
        if should_close:
            db.close()

def notify_payment_success(user_id: int, order_no: str, amount: float, item_name: str):
    create_notification(
        user_id=user_id,
        notification_type=NotificationType.PAYMENT_SUCCESS,
        title="支付成功",
        content=f"您购买的「{item_name}」支付成功，金额 ¥{amount:.2f}",
        data={"order_no": order_no, "amount": amount, "item_name": item_name},
    )

def notify_employee_execution_done(user_id: int, employee_id: str, task: str, status: str):
    create_notification(
        user_id=user_id,
        notification_type=NotificationType.EMPLOYEE_EXECUTION_DONE,
        title="员工执行完成",
        content=f"员工 {employee_id} 的任务「{task}」执行{('成功' if status == 'success' else '失败')}",
        data={"employee_id": employee_id, "task": task, "status": status},
    )

def notify_quota_warning(user_id: int, quota_type: str, remaining: int, total: int):
    usage_pct = (1 - remaining / total) * 100 if total > 0 else 0
    if usage_pct < 80:
        return  # 低于 80% 不通知
    
    create_notification(
        user_id=user_id,
        notification_type=NotificationType.QUOTA_WARNING,
        title="配额预警",
        content=f"您的 {quota_type} 配额已使用 {usage_pct:.0f}%，剩余 {remaining}",
        data={"quota_type": quota_type, "remaining": remaining, "total": total},
    )
```

**数据库模型补充**（`models.py`）：

```python
class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    type = Column(String(32), nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    data_json = Column(Text, default="{}")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**API 层**（`notification_api.py`）：

```python
"""通知 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.models import Notification, get_session_factory
from modstore_server.market_api import _get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

def get_db():
    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()

@router.get("/")
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "content": n.content,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ],
        "unread_count": db.query(Notification).filter(
            Notification.user_id == user.id,
            Notification.is_read == False,
        ).count(),
    }

@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, db: Session = Depends(get_db), user = Depends(_get_current_user)):
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not notif:
        raise HTTPException(404, "通知不存在")
    notif.is_read = True
    db.commit()
    return {"ok": True}

@router.post("/read-all")
async def mark_all_read(db: Session = Depends(get_db), user = Depends(_get_current_user)):
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}
```

**在关键位置插入通知调用**：

1. `payment_api.py` 的 `_fulfill_paid_order` 中支付成功后调用 `notify_payment_success`
2. `employee_executor.py` 的执行完成后调用 `notify_employee_execution_done`
3. `quota_middleware.py` 中配额不足时调用 `notify_quota_warning`

### 4.3 配额检查中间件全面接入

**现状**：`quota_middleware.py` 存在但未在所有关键接口调用。

**修复方案**：

1. **在 `app.py` 中为关键路由添加依赖**：

```python
from modstore_server.quota_middleware import check_employee_creation_quota, check_llm_call_quota

# 创建员工前检查配额
@router.post("/api/employees")
async def create_employee(..., _=Depends(check_employee_creation_quota)):
    pass

# LLM 聊天前检查配额
@router.post("/api/llm/chat")
async def llm_chat(..., _=Depends(check_llm_call_quota)):
    pass

# 工作流执行前检查配额
@router.post("/api/workflow/{workflow_id}/execute")
async def execute_workflow(..., _=Depends(check_llm_call_quota)):
    pass
```

1. **前端配额展示**：在 `WalletView.vue` 的「我的套餐」区域实时显示剩余配额。

### 4.4 退款/售后流程

**新增文件**：`modstore_server/refund_api.py`

```python
"""退款申请 API（用户端）。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modstore_server.models import Order, RefundRequest, get_session_factory
from modstore_server.market_api import _get_current_user

router = APIRouter(prefix="/api/refunds", tags=["refunds"])

def get_db():
    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()

class RefundApplyBody(BaseModel):
    order_no: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=5, max_length=1000)

@router.post("/apply")
async def apply_refund(
    body: RefundApplyBody,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    # 查找订单
    order = db.query(Order).filter(
        Order.order_no == body.order_no,
        Order.user_id == user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "paid":
        raise HTTPException(400, "只有已支付订单可申请退款")
    
    # 检查是否已有退款申请
    existing = db.query(RefundRequest).filter(
        RefundRequest.order_no == body.order_no,
    ).first()
    if existing:
        raise HTTPException(400, "该订单已有退款申请")
    
    # 创建退款申请
    refund = RefundRequest(
        user_id=user.id,
        order_no=body.order_no,
        amount=order.amount,
        reason=body.reason,
        status="pending",
    )
    db.add(refund)
    db.commit()
    
    # 发送通知给管理员
    from modstore_server.notification_service import create_notification, NotificationType
    # TODO: 查找管理员用户并发送通知
    
    return {"ok": True, "refund_id": refund.id}

@router.get("/my")
async def my_refunds(db: Session = Depends(get_db), user = Depends(_get_current_user)):
    refunds = db.query(RefundRequest).filter(RefundRequest.user_id == user.id).all()
    return {
        "refunds": [
            {
                "id": r.id,
                "order_no": r.order_no,
                "amount": r.amount,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in refunds
        ]
    }
```

**数据库模型补充**：

```python
class RefundRequest(Base):
    __tablename__ = "refund_requests"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    order_no = Column(String(64), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), default="pending")  # pending, approved, rejected
    admin_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## 五、P2 修复：运营与优化

### 5.1 使用统计面板

**后端 API**（`modstore_server/analytics_api.py`）：

```python
"""使用统计 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from modstore_server.models import EmployeeExecutionMetric, Order, User, get_session_factory
from modstore_server.market_api import _get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

def get_db():
    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()

@router.get("/dashboard")
async def dashboard(db: Session = Depends(get_db), user = Depends(_get_current_user)):
    """用户仪表盘数据。"""
    # 执行统计
    total_exec = db.query(EmployeeExecutionMetric).filter(
        EmployeeExecutionMetric.user_id == user.id,
    ).count()
    
    success_exec = db.query(EmployeeExecutionMetric).filter(
        EmployeeExecutionMetric.user_id == user.id,
        EmployeeExecutionMetric.status == "success",
    ).count()
    
    total_tokens = db.query(func.sum(EmployeeExecutionMetric.llm_tokens)).filter(
        EmployeeExecutionMetric.user_id == user.id,
    ).scalar() or 0
    
    # 消费统计
    total_spent = db.query(func.sum(Order.amount)).filter(
        Order.user_id == user.id,
        Order.status == "paid",
    ).scalar() or 0
    
    # 最近执行
    recent = db.query(EmployeeExecutionMetric).filter(
        EmployeeExecutionMetric.user_id == user.id,
    ).order_by(EmployeeExecutionMetric.id.desc()).limit(10).all()
    
    return {
        "execution": {
            "total": total_exec,
            "success": success_exec,
            "failed": total_exec - success_exec,
            "success_rate": (success_exec / total_exec * 100) if total_exec > 0 else 0,
            "total_tokens": int(total_tokens),
        },
        "spending": {
            "total": round(total_spent, 2),
        },
        "recent_executions": [
            {
                "id": r.id,
                "employee_id": r.employee_id,
                "task": r.task,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "llm_tokens": r.llm_tokens,
                "created_at": r.created_at.isoformat(),
            }
            for r in recent
        ],
    }
```

**前端页面**：新增 `AnalyticsView.vue`，展示执行统计、消费趋势、最近活动等。

### 5.2 部署监控与告警

**新增文件**：`modstore_server/health_api.py`

```python
"""健康检查 API。"""

import os
from datetime import datetime

from fastapi import APIRouter

from modstore_server.models import get_session_factory

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/")
async def health_check():
    checks = {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": os.environ.get("MODSTORE_VERSION", "unknown"),
    }
    
    # 数据库检查
    try:
        sf = get_session_factory()
        with sf() as session:
            session.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"
    
    return checks

@router.get("/ready")
async def readiness_check():
    """Kubernetes readiness probe。"""
    return {"ready": True}

@router.get("/live")
async def liveness_check():
    """Kubernetes liveness probe。"""
    return {"alive": True}
```

**Nginx 配置补充**：

```nginx
# 健康检查端点（不经过认证）
location /health {
    proxy_pass http://backend;
    proxy_connect_timeout 5s;
}
```

### 5.3 工作台首页改造

根据 `.trae/documents/工作台页面改造计划.md` 执行：

1. **路由重定向**：`/` → `/workbench`
2. **新增 `WorkbenchHomeView.vue`**：
  - 快速开始卡片（制作员工、创建工作流、浏览商店）
  - 最近活动（最近执行的员工、最近编辑的工作流）
  - 配额概览
  - 推荐/热门员工

---

## 六、数据库迁移

### 6.1 新增表

执行以下 SQL：

```sql
-- 通知表
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type VARCHAR(32) NOT NULL,
    title VARCHAR(256) NOT NULL,
    content TEXT NOT NULL,
    data_json TEXT DEFAULT '{}',
    is_read BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
CREATE INDEX idx_notifications_user_read ON notifications(user_id, is_read);

-- 退款申请表
CREATE TABLE IF NOT EXISTS refund_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    order_no VARCHAR(64) NOT NULL,
    amount FLOAT NOT NULL,
    reason TEXT NOT NULL,
    status VARCHAR(16) DEFAULT 'pending',
    admin_note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_refund_user_id ON refund_requests(user_id);
CREATE INDEX idx_refund_order_no ON refund_requests(order_no);
```

### 6.2 现有表字段补充

```sql
-- EmployeeExecutionMetric 添加 llm_tokens 字段（如果缺失）
ALTER TABLE employee_execution_metrics ADD COLUMN llm_tokens INTEGER DEFAULT 0;
```

---

## 七、前端修复清单

### 7.1 新增页面/组件


| 文件                                        | 说明     |
| ----------------------------------------- | ------ |
| `market/src/views/AnalyticsView.vue`      | 使用统计面板 |
| `market/src/views/NotificationCenter.vue` | 消息通知中心 |
| `market/src/views/RefundApplyView.vue`    | 退款申请页面 |
| `market/src/views/WorkbenchHomeView.vue`  | 工作台首页  |


### 7.2 修改现有页面


| 文件                                  | 修改内容                           |
| ----------------------------------- | ------------------------------ |
| `market/src/views/WalletView.vue`   | 添加「我的套餐」配额实时展示                 |
| `market/src/views/WorkflowView.vue` | 添加触发器配置面板（cron/webhook）        |
| `market/src/App.vue`                | 添加通知中心入口（右上角铃铛图标）              |
| `market/src/router/index.js`        | 添加新路由，设置 `/` 重定向到 `/workbench` |


### 7.3 API 调用封装

新增 `market/src/api/notifications.js`：

```javascript
import axios from 'axios';

export const fetchNotifications = (unreadOnly = false) => 
  axios.get('/api/notifications', { params: { unread_only: unreadOnly } });

export const markNotificationRead = (id) => 
  axios.post(`/api/notifications/${id}/read`);

export const markAllNotificationsRead = () => 
  axios.post('/api/notifications/read-all');
```

---

## 八、依赖安装清单

```bash
# 进入 Python 环境
cd MODstore_deploy/modstore_server

# 新增依赖
pip install apscheduler openpyxl pandas

# 更新 requirements.txt
echo "apscheduler>=3.10.0" >> requirements.txt
echo "openpyxl>=3.1.0" >> requirements.txt
echo "pandas>=2.0.0" >> requirements.txt
```

---

## 九、测试验证清单

### 9.1 P0 验证

- 创建员工 → 配置 LLM 模型 → 执行员工任务 → 确认 LLM 被调用并返回结果
- 配置 Actions（http_request）→ 执行员工 → 确认 HTTP 请求发出
- 创建工作流 → 添加员工节点 → 执行工作流 → 确认员工真实执行
- 检查 `EmployeeExecutionMetric` 表中 `llm_tokens` 有值

### 9.2 P1 验证

- 配置 cron 触发器 → 等待触发时间 → 确认工作流自动执行
- 配置 webhook 触发器 → 调用 webhook → 确认工作流执行
- 支付成功 → 确认收到站内通知
- 员工执行完成 → 确认收到站内通知
- 申请退款 → 确认退款记录创建

### 9.3 P2 验证

- 访问 `/health` → 确认返回健康状态
- 访问统计面板 → 确认数据展示正确
- 工作台首页 → 确认快速入口和最近活动展示

---

## 十、实施建议

### 阶段一（1-2 天）：P0 核心修复

1. 实现 `_cognition_real` 接入 LLM
2. 实现 `_actions_real` 工具调用
3. 实现 `_perception_real` 输入解析
4. 修改 `workflow_engine.py` 传递 user_id
5. 验证员工真实执行

### 阶段二（2-3 天）：P1 体验完善

1. 实现工作流触发器调度器
2. 实现消息通知系统
3. 接入配额检查中间件
4. 实现退款申请流程

### 阶段三（1-2 天）：P2 运营优化

1. 实现使用统计面板
2. 实现健康检查 API
3. 改造工作台首页
4. 全面测试验证

---

## 十一、风险与注意事项

1. **LLM 调用成本**：真实接入 LLM 后会产生 API 调用费用，确保用户已配置 API Key 或平台已配置环境变量
2. **并发安全**：`execute_employee_task` 使用 `ThreadPoolExecutor` 做超时控制，确保线程安全
3. **数据库迁移**：新增表和字段需要谨慎执行，建议先备份数据库
4. **向后兼容**：保留 `mock_employees=True` 的沙盒模式，确保调试不受影响
5. **错误处理**：LLM 调用失败时应有优雅降级，返回错误信息而不是崩溃

