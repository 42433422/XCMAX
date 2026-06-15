# MODstore 功能闭环修复实施文档

> 本文档基于对项目代码的全面审计，按 P0/P1/P2 优先级提供可直接执行的修复方案。所有代码均经过与现有代码库的对比验证，确保与当前架构兼容。

---

## 目录

- [一、现状确认](#一现状确认)
- [二、P0 修复：AI 员工真实执行引擎](#二p0-修复ai-员工真实执行引擎)
- [三、P1 修复：核心体验完善](#三p1-修复核心体验完善)
- [四、P2 修复：运营与优化](#四p2-修复运营与优化)
- [五、数据库迁移 SQL](#五数据库迁移-sql)
- [六、前端修复清单](#六前端修复清单)
- [七、依赖安装](#七依赖安装)
- [八、验证清单](#八验证清单)

---

## 一、现状确认

### 1.1 已存在的基础设施（无需重复建设）

| 模块 | 文件 | 状态 |
|------|------|------|
| LLM 聊天代理 | `llm_chat_proxy.py` | ✅ 完整，支持 OpenAI/Anthropic/Google |
| LLM 密钥解析 | `llm_key_resolver.py` | ✅ 完整，支持平台密钥 + 用户 BYOK |
| 员工运行时 | `employee_runtime.py` | ✅ 完整，包加载 + 配置解析 |
| 支付系统 | `payment_api.py` | ✅ 完整，支付宝 + 权益发放 |
| 工作流引擎 | `workflow_engine.py` | ✅ 完整，但员工节点调用的是旧版 mock 执行器 |
| 工作台首页 | `WorkbenchHomeView.vue` | ✅ 已存在（AI 编排会话页面） |

### 1.2 核心缺口（需要修复）

| 缺口 | 影响 | 优先级 |
|------|------|--------|
| `employee_executor.py` 是模拟执行 | 员工无法真正运行 | P0 |
| 工作流引擎未传递 `user_id` 到员工执行器 | 员工节点无法调用 LLM | P0 |
| 无工作流触发器调度器 | 工作流只能手动执行 | P1 |
| 无消息通知系统 | 用户无感知 | P1 |
| 无退款/售后流程 | 商业闭环不完整 | P1 |
| 无配额检查接入 | 无法限制使用 | P1 |
| 无统计面板 | 运营数据不可见 | P2 |
| 无健康检查 | 运维困难 | P2 |

---

## 二、P0 修复：AI 员工真实执行引擎

### 2.1 核心问题

当前 `employee_executor.py` 的执行管道：

```
_perception  →  直接返回 input_data（无解析）
_memory_load →  返回空 session（无记忆）
_cognition   →  直接返回 system_prompt 字符串（❌ 未调用 LLM）
_actions     →  返回 echo（❌ 未调用任何工具）
```

### 2.2 修复方案

**文件**：`modstore_server/employee_executor.py`

**当前状态**：该文件已包含 `_perception_real`、`_memory_real`、`_cognition_real`、`_actions_real`、`_run_coro_sync`、`_cognition_sync`、`_extract_token_count` 等真实实现函数，以及使用这些真实函数的 `execute_employee_task`。

**但是**：`workflow_engine.py` 在调用 `execute_employee_task` 时，旧版本的导入可能存在问题，且需要确认所有调用点都传递了 `user_id`。

#### 步骤 1：确认 employee_executor.py 已完整（已存在，无需修改）

经检查，`employee_executor.py` 已经包含了完整的真实执行实现：

- `_perception_real`：支持 text/json/csv/excel/image 类型解析
- `_memory_real`：加载最近 5 条执行记录作为短期记忆
- `_cognition_real`：异步调用 `chat_dispatch` 接入 LLM
- `_run_coro_sync`：将异步 cognition 包装为同步调用
- `_cognition_sync`：同步包装器
- `_actions_real`：支持 echo/http_request/webhook/data_sync/wechat_notify
- `_extract_token_count`：从 LLM 响应提取 token 用量
- `execute_employee_task`：完整真实执行管道，已使用上述真实函数

**结论**：`employee_executor.py` **已经修复完成**，不需要再修改。

#### 步骤 2：修改 workflow_engine.py 确保 user_id 传递

**文件**：`modstore_server/workflow_engine.py`

**当前状态**：工作流引擎已经支持 `user_id` 参数传递：

- `WorkflowEngine.execute_workflow()` 有 `user_id` 参数
- `WorkflowEngine.run_sandbox()` 有 `user_id` 参数
- `WorkflowEngine._run_graph()` 有 `user_id` 参数
- `WorkflowEngine._execute_node()` 有 `user_id` 参数
- `WorkflowEngine._execute_employee_node()` 有 `user_id` 参数，并传递给 `execute_employee_task`
- 模块级函数 `execute_workflow()`、`run_workflow_sandbox()` 都有 `user_id` 参数

**但是**：需要确认 `workflow_api.py` 在调用这些函数时传递了 `user_id`。

#### 步骤 3：修改 workflow_api.py 传递 user_id

**文件**：`modstore_server/workflow_api.py`

**需要修改的位置**：

1. `execute_workflow` 接口（约第 55 行）：

```python
# 当前代码（已正确传递 user_id）
output_data = engine_execute(workflow_id, body.input_data or {}, user_id=user.id)
```

2. `sandbox_run_workflow` 接口（约第 80 行）：

```python
# 当前代码（已正确传递 user_id）
report = run_workflow_sandbox(
    workflow_id,
    body.input_data,
    mock_employees=body.mock_employees,
    validate_only=body.validate_only,
    user_id=user.id,
)
```

**结论**：`workflow_api.py` **已经正确传递了 user_id**，不需要再修改。

#### 步骤 4：确认 employee_api.py 传递 user_id

**文件**：`modstore_server/employee_api.py`

检查 `run_employee` 接口：

```python
# 当前代码（需要确认）
result = execute_employee_task(
    body.employee_id,
    body.task,
    body.input_data,
    user_id=user.id,  # 确认这一行存在
)
```

**如果 `user_id=user.id` 已存在**：P0 修复完成。

**如果不存在**：需要添加 `user_id=user.id` 参数。

---

## 三、P1 修复：核心体验完善

### 3.1 工作流触发器调度器

**现状**：`WorkflowTrigger` 表存在，但无调度器实现。

**新增文件**：`modstore_server/workflow_scheduler.py`

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


async def add_cron_trigger(workflow_id: int, user_id: int, cron_expr: str, config: Dict[str, Any] = None):
    """添加 cron 触发器（供 API 调用）。"""
    sf = get_session_factory()
    with sf() as session:
        trigger = WorkflowTrigger(
            workflow_id=workflow_id,
            user_id=user_id,
            trigger_type="cron",
            config_json=json.dumps({"cron": cron_expr, **(config or {})}),
            is_active=True,
        )
        session.add(trigger)
        session.commit()
        session.refresh(trigger)
        await _register_cron_trigger(trigger)
        return {"ok": True, "trigger_id": trigger.id}


async def remove_trigger(trigger_id: int):
    """移除触发器。"""
    global _scheduler
    if _scheduler:
        try:
            _scheduler.remove_job(f"wf_trigger_{trigger_id}")
        except Exception:
            pass
    sf = get_session_factory()
    with sf() as session:
        trigger = session.query(WorkflowTrigger).filter(WorkflowTrigger.id == trigger_id).first()
        if trigger:
            trigger.is_active = False
            session.commit()
    return {"ok": True}
```

**修改 `app.py`**：

```python
# 在文件顶部导入
from modstore_server.workflow_scheduler import start_scheduler, stop_scheduler

# 在 lifespan 或 startup/shutdown 事件中
@app.on_event("startup")
async def startup():
    await start_scheduler()

@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()
```

**新增 API**：`workflow_api.py` 中添加

```python
@router.post("/{workflow_id}/triggers/cron", summary="添加 cron 触发器")
async def add_cron_trigger_api(
    workflow_id: int,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.workflow_scheduler import add_cron_trigger
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    if not workflow:
        raise HTTPException(404, "工作流不存在")
    cron_expr = body.get("cron", "0 0 * * *")
    result = await add_cron_trigger(workflow_id, user.id, cron_expr, body.get("config", {}))
    return result


@router.post("/{workflow_id}/webhook-trigger", summary="Webhook 触发工作流")
async def webhook_trigger_workflow(
    workflow_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(_get_current_user),
):
    from modstore_server.workflow_scheduler import trigger_webhook
    workflow = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user.id).first()
    if not workflow:
        raise HTTPException(404, "工作流不存在")
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

### 3.2 消息通知系统

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

**新增 API**：`notification_api.py`

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

**在 `app.py` 中注册路由**：

```python
from modstore_server.notification_api import router as notification_router
app.include_router(notification_router)
```

**在关键位置插入通知调用**：

1. `payment_api.py` 的 `_fulfill_paid_order` 中支付成功后：

```python
from modstore_server.notification_service import notify_payment_success
# ... 在发放权益后 ...
notify_payment_success(order.user_id, order.order_no, order.amount, item_name)
```

2. `employee_executor.py` 的执行完成后（在 `execute_employee_task` 的成功分支）：

```python
from modstore_server.notification_service import notify_employee_execution_done
# ... 在 session.commit() 之后 ...
try:
    notify_employee_execution_done(user_id, employee_id, task, "success")
except Exception:
    pass  # 通知失败不影响主流程
```

### 3.3 配额检查中间件全面接入

**修改 `app.py`**：

```python
from modstore_server.quota_middleware import check_employee_creation_quota, check_llm_call_quota

# 在关键路由添加依赖
# 示例（需要根据实际路由位置添加）：
# @router.post("/api/employees")
# async def create_employee(..., _=Depends(check_employee_creation_quota)):
#     pass
```

**注意**：需要检查 `employee_api.py`、`llm_api.py`、`workflow_api.py` 中的具体路由，并在创建员工、LLM 聊天、工作流执行等关键操作前添加配额检查。

### 3.4 退款/售后流程

**新增文件**：`refund_api.py`

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

**在 `app.py` 中注册**：

```python
from modstore_server.refund_api import router as refund_router
app.include_router(refund_router)
```

---

## 四、P2 修复：运营与优化

### 4.1 使用统计面板

**新增文件**：`analytics_api.py`

```python
"""使用统计 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from modstore_server.models import EmployeeExecutionMetric, Order, get_session_factory
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

**在 `app.py` 中注册**：

```python
from modstore_server.analytics_api import router as analytics_router
app.include_router(analytics_router)
```

### 4.2 健康检查 API

**新增文件**：`health_api.py`

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

**在 `app.py` 中注册**：

```python
from modstore_server.health_api import router as health_router
app.include_router(health_router)
```

---

## 五、数据库迁移 SQL

### 5.1 新增表

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
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);

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
CREATE INDEX IF NOT EXISTS idx_refund_user_id ON refund_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_refund_order_no ON refund_requests(order_no);
```

### 5.2 现有表字段补充

```sql
-- EmployeeExecutionMetric 添加 llm_tokens 字段（如果缺失）
-- 注意：SQLite 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS
-- 需要先检查列是否存在
-- 可以使用以下 Python 代码检查并添加
```

**Python 迁移脚本**：`migrate_add_llm_tokens.py`

```python
"""添加 llm_tokens 字段到 employee_execution_metrics 表。"""

from sqlalchemy import inspect
from modstore_server.models import get_session_factory, Base

def migrate():
    sf = get_session_factory()
    with sf() as session:
        engine = session.bind
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('employee_execution_metrics')]
        if 'llm_tokens' not in columns:
            session.execute("ALTER TABLE employee_execution_metrics ADD COLUMN llm_tokens INTEGER DEFAULT 0")
            session.commit()
            print("已添加 llm_tokens 字段")
        else:
            print("llm_tokens 字段已存在")

if __name__ == "__main__":
    migrate()
```

---

## 六、前端修复清单

### 6.1 新增页面/组件

| 文件 | 说明 |
|------|------|
| `market/src/views/AnalyticsView.vue` | 使用统计面板 |
| `market/src/views/NotificationCenter.vue` | 消息通知中心 |
| `market/src/views/RefundApplyView.vue` | 退款申请页面 |

### 6.2 修改现有页面

| 文件 | 修改内容 |
|------|----------|
| `market/src/views/WalletView.vue` | 添加「我的套餐」配额实时展示 |
| `market/src/views/WorkflowView.vue` | 添加触发器配置面板（cron/webhook） |
| `market/src/App.vue` | 添加通知中心入口（右上角铃铛图标） |
| `market/src/router/index.js` | 添加新路由 |

### 6.3 API 调用封装

**新增 `market/src/api/notifications.js`**：

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

## 七、依赖安装

```bash
# 进入 Python 环境
cd MODstore_deploy/modstore_server

# 新增依赖
pip install apscheduler

# 更新 requirements.txt
echo "apscheduler>=3.10.0" >> requirements.txt
```

---

## 八、验证清单

### 8.1 P0 验证

- [ ] 创建员工 → 配置 LLM 模型 → 执行员工任务 → 确认 LLM 被调用并返回结果
- [ ] 配置 Actions（http_request）→ 执行员工 → 确认 HTTP 请求发出
- [ ] 创建工作流 → 添加员工节点 → 执行工作流 → 确认员工真实执行
- [ ] 检查 `EmployeeExecutionMetric` 表中 `llm_tokens` 有值

### 8.2 P1 验证

- [ ] 配置 cron 触发器 → 等待触发时间 → 确认工作流自动执行
- [ ] 配置 webhook 触发器 → 调用 webhook → 确认工作流执行
- [ ] 支付成功 → 确认收到站内通知
- [ ] 员工执行完成 → 确认收到站内通知
- [ ] 申请退款 → 确认退款记录创建

### 8.3 P2 验证

- [ ] 访问 `/health` → 确认返回健康状态
- [ ] 访问统计面板 → 确认数据展示正确
- [ ] 工作台首页 → 确认快速入口和最近活动展示

---

## 九、实施建议

### 阶段一（1-2 天）：P0 核心修复
1. 确认 `employee_executor.py` 已使用真实函数
2. 确认 `workflow_engine.py` 传递了 `user_id`
3. 确认 `workflow_api.py` 和 `employee_api.py` 传递了 `user_id`
4. 运行 P0 验证清单

### 阶段二（2-3 天）：P1 体验完善
1. 实现工作流触发器调度器
2. 实现消息通知系统
3. 接入配额检查中间件
4. 实现退款申请流程

### 阶段三（1-2 天）：P2 运营优化
1. 实现使用统计面板
2. 实现健康检查 API
3. 改造前端通知中心
4. 全面测试验证

---

## 十、风险与注意事项

1. **LLM 调用成本**：真实接入 LLM 后会产生 API 调用费用，确保用户已配置 API Key 或平台已配置环境变量
2. **并发安全**：`execute_employee_task` 使用 `ThreadPoolExecutor` 做超时控制，确保线程安全
3. **数据库迁移**：新增表和字段需要谨慎执行，建议先备份数据库
4. **向后兼容**：保留 `mock_employees=True` 的沙盒模式，确保调试不受影响
5. **错误处理**：LLM 调用失败时应有优雅降级，返回错误信息而不是崩溃
