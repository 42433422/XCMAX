# MODstore 全功能逻辑闭环修复总纲

> 本文档基于 2026-04-26 对项目全部代码（Python 后端 / Vue 前端 / Java 支付服务 / 门户网站）的全面审计，梳理从「注册 → 浏览 → 购买 → 支付 → 权益发放 → 员工执行 → 工作流编排 → 通知 → 退款 → 复购」全链路缺口，并提供可直接执行的修复方案。
>
> 前序文档《MODstore功能闭环修复计划.md》和《MODstore_P0_P1_P2修复实施文档.md》已覆盖"AI 员工真实执行引擎"相关修复（P0 员工执行器、P1 触发器/通知/退款/配额、P2 统计/健康检查），**本文档不再重复**，聚焦于前序文档未覆盖的新发现缺口。

---

## 目录

- [一、闭环完成度总览](#一闭环完成度总览)
- [二、P0 修复：安全与关键逻辑（阻断闭环）](#二p0-修复安全与关键逻辑阻断闭环)
- [三、P1 修复：核心体验完善](#三p1-修复核心体验完善)
- [四、P2 修复：运营与体验优化](#四p2-修复运营与体验优化)
- [五、P3 修复：扩展与部署](#五p3-修复扩展与部署)
- [六、数据库迁移 SQL](#六数据库迁移-sql)
- [七、前端修复清单](#七前端修复清单)
- [八、依赖安装](#八依赖安装)
- [九、验证清单](#九验证清单)
- [十、实施路线图](#十实施路线图)
- [十一、风险与注意事项](#十一风险与注意事项)

---

## 一、闭环完成度总览

### 1.1 核心商业闭环

```
用户注册/登录 → 浏览市场 → 购买员工/套餐 → 支付(支付宝) → 权益发放 →
员工真实执行(感知→记忆→认知→行动) → 工作流编排 → 触发器自动执行 →
通知反馈 → 配额管理 → 退款售后 → 持续复购
```

### 1.2 各模块完成度

| 模块 | 完成度 | 关键缺口 |
|------|--------|---------|
| 用户注册/登录 | 85% | 缺忘记密码、Token 刷新、用户资料编辑 |
| 商品浏览/购买 | 70% | 购买与支付衔接断裂、缺评价/购物车 |
| 支付/钱包 | 75% | 金额校验、幂等性、并发安全、微信支付 |
| 权益发放 | 80% | Java 端逻辑错误、权益验证接口缺失 |
| AI 员工制作 | 75% | 向导与 BlockBuilder 关系不清、模板联动 |
| AI 员工执行 | 50% | Excel/OCR/知识库/微信通知均为占位 |
| 工作流编排 | 70% | 连线交互不完整、无版本管理 |
| 退款售后 | 40% | 无管理员审核、无支付宝退款接口调用 |
| 通知系统 | 60% | 无实时推送、无分类/角标/跳转 |
| 门户网站 | 50% | 内容为示例、表单无后端、无产品截图 |
| 公网部署 | 30% | HTTPS/域名/生产密钥/数据库迁移均未完成 |

**整体闭环完成度：≈ 60%**

### 1.3 前序文档已覆盖的修复（本文档不重复）

| 修复项 | 文档 |
|--------|------|
| 员工真实执行引擎（_cognition_real / _actions_real / _perception_real / _memory_real） | MODstore_P0_P1_P2修复实施文档.md |
| 工作流触发器调度器（workflow_scheduler.py） | MODstore_P0_P1_P2修复实施文档.md |
| 消息通知系统（notification_service.py / notification_api.py） | MODstore_P0_P1_P2修复实施文档.md |
| 配额检查中间件接入 | MODstore_P0_P1_P2修复实施文档.md |
| 退款申请 API（用户端 refund_api.py） | MODstore_P0_P1_P2修复实施文档.md |
| 使用统计面板（analytics_api.py） | MODstore_P0_P1_P2修复实施文档.md |
| 健康检查 API（health_api.py） | MODstore_P0_P1_P2修复实施文档.md |

---

## 二、P0 修复：安全与关键逻辑（阻断闭环）

### 2.1 支付宝异步通知金额校验

**严重程度**：🔴 阻断级 — 攻击者可伪造小额支付冒充大额订单

**涉及文件**：
- `modstore_server/payment_api.py`（Python 后端）
- `modstore_server/alipay_service.py`（Python 后端）

**现状**：支付宝异步通知处理时，未将返回的 `total_amount` 与数据库中订单金额比对。

**修复方案**：

在 `payment_api.py` 的支付宝通知处理函数中添加金额校验：

```python
# payment_api.py — 在处理支付宝通知的位置添加

def _verify_alipay_notification(params: dict, db_session) -> dict:
    """校验支付宝异步通知：验签 + 金额比对 + 幂等性。"""
    from modstore_server.alipay_service import verify_alipay_signature

    # 1. 验签
    if not verify_alipay_signature(params):
        return {"ok": False, "error": "签名验证失败"}

    out_trade_no = params.get("out_trade_no", "")
    trade_status = params.get("trade_status", "")
    total_amount_str = params.get("total_amount", "0")

    # 2. 查询订单
    order = db_session.query(Order).filter(Order.order_no == out_trade_no).first()
    if not order:
        return {"ok": False, "error": "订单不存在"}

    # 3. 金额校验（关键！）
    try:
        paid_amount = float(total_amount_str)
    except (ValueError, TypeError):
        return {"ok": False, "error": f"无效的金额: {total_amount_str}"}

    if abs(paid_amount - order.amount) > 0.01:
        return {
            "ok": False,
            "error": f"金额不匹配: 订单={order.amount}, 实付={paid_amount}",
        }

    # 4. 幂等性：已处理的订单直接返回成功
    if order.status == "paid":
        return {"ok": True, "already_processed": True}

    # 5. 状态校验
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        return {"ok": False, "error": f"非成功状态: {trade_status}"}

    return {"ok": True, "order": order, "paid_amount": paid_amount}
```

**调用位置**：替换现有的通知处理逻辑，确保所有通知都经过此函数校验。

---

### 2.2 支付宝异步通知幂等性保障

**严重程度**：🔴 阻断级 — 支付宝可能多次发送同一通知，导致权益重复发放

**涉及文件**：`modstore_server/payment_api.py`

**修复方案**：

在 `_fulfill_paid_order` 入口处添加状态检查：

```python
def _fulfill_paid_order(order, db_session):
    """支付成功后发放权益（幂等）。"""
    # 幂等性检查：如果订单已经是 paid 状态且已发放，直接返回
    if order.status == "paid" and order.fulfilled:
        logger.info("订单已处理，跳过重复发放: order_no=%s", order.order_no)
        return {"ok": True, "already_fulfilled": True}

    # 更新订单状态
    order.status = "paid"
    order.paid_at = datetime.utcnow()

    # ... 后续权益发放逻辑 ...

    order.fulfilled = True
    db_session.commit()
```

---

### 2.3 员工执行权限校验

**严重程度**：🔴 阻断级 — 任何登录用户可执行任何员工，无权益检查

**涉及文件**：`modstore_server/employee_api.py`

**现状**：`run_employee` 接口仅检查用户是否登录，未检查用户是否购买了该员工或拥有相应权益。

**修复方案**：

```python
# employee_api.py — 在 run_employee 接口中添加权限校验

def _check_employee_access(user_id: int, employee_id: str, db_session) -> bool:
    """检查用户是否有权执行该员工。"""
    from modstore_server.models import Entitlement, CatalogItem

    # 1. 检查是否是员工创建者
    catalog_item = db_session.query(CatalogItem).filter(
        CatalogItem.employee_id == employee_id,
    ).first()
    if catalog_item and catalog_item.owner_id == user_id:
        return True

    # 2. 检查是否购买了该员工
    entitlement = db_session.query(Entitlement).filter(
        Entitlement.user_id == user_id,
        Entitlement.catalog_id == catalog_item.id if catalog_item else 0,
        Entitlement.active == True,
    ).first()
    if entitlement:
        return True

    # 3. 检查是否有有效套餐（套餐可能包含员工执行权限）
    from modstore_server.models import UserPlan
    active_plan = db_session.query(UserPlan).filter(
        UserPlan.user_id == user_id,
        UserPlan.active == True,
        UserPlan.expires_at > datetime.utcnow(),
    ).first()
    if active_plan:
        return True

    return False


# 在 run_employee 接口中调用
@router.post("/run")
async def run_employee(
    body: RunEmployeeBody,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    if not _check_employee_access(user.id, body.employee_id, db):
        raise HTTPException(403, "您无权执行该员工，请先购买或订阅套餐")

    result = execute_employee_task(
        body.employee_id,
        body.task,
        body.input_data,
        user_id=user.id,
    )
    return result
```

---

### 2.4 前端支付签名安全加固

**严重程度**：🔴 阻断级 — 签名密钥在前端暴露，形同虚设

**涉及文件**：
- `market/src/api.js`（前端）
- `modstore_server/payment_api.py`（后端）

**现状**：
- 前端 `generateSignature()` 使用 `VITE_PAYMENT_SECRET` 生成签名
- 默认回退 `'default_secret_key'`，生产环境若未配置将使用弱密钥
- 前端密钥可被浏览器开发者工具查看，签名机制可被绕过

**修复方案**：将签名生成移至后端

**步骤 1：后端新增签名接口**

```python
# payment_api.py — 新增签名接口

@router.post("/sign-checkout", summary="生成支付签名（后端签名）")
async def sign_checkout(
    body: CheckoutSignBody,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    """后端生成支付签名，避免前端暴露密钥。"""
    import hashlib
    import time
    import uuid

    request_id = str(uuid.uuid4())
    timestamp = str(int(time.time()))

    secret = os.environ.get("PAYMENT_SECRET_KEY", "default_secret_key")

    sign_data = {
        "item_id": body.item_id or "",
        "plan_id": body.plan_id or "",
        "request_id": request_id,
        "subject": body.subject,
        "timestamp": timestamp,
        "total_amount": str(body.total_amount),
        "wallet_recharge": "true" if body.wallet_recharge else "false",
    }

    sorted_keys = sorted(sign_data.keys())
    sign_str = "&".join(f"{k}={sign_data[k]}" for k in sorted_keys)
    signature = hashlib.sha256(f"{sign_str}{secret}".encode()).hexdigest()

    return {
        "request_id": request_id,
        "timestamp": timestamp,
        "signature": signature,
    }
```

**步骤 2：前端改为调用后端签名**

```javascript
// api.js — 替换前端签名逻辑

async function paymentCheckout(params) {
  // 从后端获取签名
  const signResult = await fetchWithAuth('/api/payment/sign-checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      item_id: params.item_id || '',
      plan_id: params.plan_id || '',
      subject: params.subject,
      total_amount: params.total_amount,
      wallet_recharge: params.wallet_recharge || false,
    }),
  });

  if (!signResult.ok) throw new Error('签名请求失败');

  const signData = await signResult.json();

  // 使用后端返回的签名发起支付
  return fetchWithAuth('/api/payment/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...params,
      request_id: signData.request_id,
      timestamp: signData.timestamp,
      signature: signData.signature,
    }),
  });
}
```

**步骤 3：移除前端密钥**

```javascript
// api.js — 删除以下函数
// function paymentSecretKey() { ... }
// function generateSignature(data) { ... }
```

---

### 2.5 Java 支付服务决策：修复或弃用

**严重程度**：🔴 阻断级 — Java 支付服务当前完全不可用

**涉及文件**：`java_payment_service/` 整个目录

**现状问题汇总**：

| 问题 | 严重程度 |
|------|---------|
| 无 JWT 认证过滤器，所有认证请求返回 403 | 严重 |
| 无登录/注册接口 | 严重 |
| 所有 Controller 硬编码 user.setId(1L) | 严重 |
| AuthController 返回硬编码用户 | 严重 |
| fulfillOrder 对所有订单类型都执行钱包充值 | 严重 |
| 无退款代码 | 严重 |
| 钱包无并发控制（双花风险） | 严重 |
| 金额使用 double 类型 | 高 |
| 手写 JSON 序列化不处理转义 | 高 |
| AlipayConfig Request Bean 线程不安全 | 高 |

**决策建议**：

**方案 A：弃用 Java 支付服务（推荐）**

Python 后端的支付系统（`payment_api.py` + `alipay_service.py`）已经完整可用，且与前端已对接。Java 支付服务当前处于原型/脚手架阶段，修复成本远高于收益。

- 从部署流程中移除 Java 服务
- 在文档中标注 Java 服务为"实验性/未完成"
- 专注完善 Python 后端支付系统

**方案 B：修复 Java 支付服务（如需独立扩展）**

如需保留 Java 服务作为未来微服务拆分的基础，需按以下顺序修复：

1. 实现 JWT 认证体系（JwtAuthenticationFilter + JwtUtil + 登录/注册接口）
2. 修复所有 Controller 从 SecurityContext 获取真实用户
3. 修复 fulfillOrder 按 orderKind 分别处理
4. 金额类型从 double 改为 BigDecimal
5. 钱包添加乐观锁（@Version）
6. 替换手写 mapToJson 为 Jackson ObjectMapper
7. AlipayConfig Request 对象改为方法内局部变量
8. 实现退款全流程

---

### 2.6 Catalog 双存储数据同步

**严重程度**：🔴 阻断级 — JSON 文件 + SQLite 双存储数据不一致

**涉及文件**：
- `modstore_server/catalog_store.py`
- `modstore_server/catalog_api.py`

**现状**：商品目录同时存在于 JSON 文件（`data/catalog.json`）和 SQLite 数据库中，两者之间无同步机制，导致数据不一致。

**修复方案**：以 SQLite 为唯一数据源，JSON 文件仅作为初始导入

```python
# catalog_store.py — 添加同步函数

def sync_catalog_from_json(db_session):
    """从 JSON 文件导入目录到数据库（仅首次或手动触发）。"""
    import json
    from pathlib import Path

    json_path = Path(__file__).parent / "data" / "catalog.json"
    if not json_path.exists():
        return {"imported": 0}

    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    imported = 0
    for item_data in items:
        existing = db_session.query(CatalogItem).filter(
            CatalogItem.catalog_id == item_data.get("id"),
        ).first()
        if not existing:
            catalog_item = CatalogItem(
                catalog_id=item_data.get("id"),
                name=item_data.get("name", ""),
                description=item_data.get("description", ""),
                category=item_data.get("category", ""),
                industry=item_data.get("industry", ""),
                price=item_data.get("price", 0),
                employee_id=item_data.get("employee_id"),
                owner_id=item_data.get("owner_id", 0),
                version=item_data.get("version", "1.0.0"),
                status="stable",
            )
            db_session.add(catalog_item)
            imported += 1

    db_session.commit()
    return {"imported": imported}


# catalog_api.py — 所有查询改为从数据库读取
# 删除所有直接读取 JSON 文件的逻辑
# 确保搜索、筛选、详情等接口统一使用 SQLAlchemy 查询
```

---

## 三、P1 修复：核心体验完善

### 3.1 退款管理员审核流程

**严重程度**：🟠 严重 — 用户可申请退款但无管理员审批

**涉及文件**：
- `modstore_server/refund_api.py`（后端，已存在用户端）
- `market/src/views/RefundApplyView.vue`（前端，已存在）

**修复方案**：

**步骤 1：后端添加管理员审核接口**

```python
# refund_api.py — 新增管理员接口

@router.get("/admin/pending", summary="管理员：待审核退款列表")
async def admin_pending_refunds(
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")

    refunds = db.query(RefundRequest).filter(
        RefundRequest.status == "pending",
    ).order_by(RefundRequest.created_at.desc()).all()

    return {
        "refunds": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "order_no": r.order_no,
                "amount": r.amount,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in refunds
        ],
        "total": len(refunds),
    }


class RefundReviewBody(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    admin_note: str = Field(default="", max_length=1000)


@router.post("/admin/{refund_id}/review", summary="管理员：审核退款")
async def admin_review_refund(
    refund_id: int,
    body: RefundReviewBody,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")

    refund = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
    if not refund:
        raise HTTPException(404, "退款申请不存在")
    if refund.status != "pending":
        raise HTTPException(400, f"退款状态为 {refund.status}，无法审核")

    if body.action == "approve":
        refund.status = "approved"
        refund.admin_note = body.admin_note

        # 调用支付宝退款接口
        try:
            from modstore_server.alipay_service import refund_order
            result = refund_order(refund.order_no, refund.amount)
            if result.get("ok"):
                refund.status = "refunded"
            else:
                refund.status = "refund_failed"
                refund.admin_note = f"{body.admin_note}\n退款失败: {result.get('error', '')}"
        except Exception as e:
            refund.status = "refund_failed"
            refund.admin_note = f"{body.admin_note}\n退款异常: {str(e)}"

    elif body.action == "reject":
        refund.status = "rejected"
        refund.admin_note = body.admin_note

    db.session.commit()

    # 通知用户
    from modstore_server.notification_service import create_notification, NotificationType
    status_text = "已通过" if refund.status in ("approved", "refunded") else "已拒绝"
    create_notification(
        user_id=refund.user_id,
        notification_type=NotificationType.SYSTEM,
        title="退款审核结果",
        content=f"您的退款申请（订单 {refund.order_no}）{status_text}。{refund.admin_note or ''}",
    )

    return {"ok": True, "status": refund.status}
```

**步骤 2：支付宝退款接口**

```python
# alipay_service.py — 新增退款函数

def refund_order(order_no: str, amount: float, reason: str = "用户申请退款") -> dict:
    """调用支付宝退款接口。"""
    from alipay import AliPay

    alipay_client = _get_alipay_client()

    request = alipay_client.api_alipay_trade_refund(
        out_trade_no=order_no,
        refund_amount=str(amount),
        refund_reason=reason,
    )

    try:
        response = alipay_client.execute(request)
        if response.get("code") == "10000":
            return {"ok": True, "fund_change": response.get("fund_change", "N")}
        else:
            return {"ok": False, "error": response.get("sub_msg", "退款失败")}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

**步骤 3：前端退款页面增强**

在 `RefundApplyView.vue` 中添加：
- 从订单列表选择订单号（而非手动输入）
- 显示退款进度时间线
- 退款政策说明
- 取消退款申请按钮

---

### 3.2 购买与支付流程衔接

**严重程度**：🟠 严重 — 付费商品无法走支付结账流程

**涉及文件**：
- `market/src/views/CatalogDetailView.vue`（前端）
- `market/src/api.js`（前端）

**现状**：`buyItem()` 是直接购买（免费/余额扣款），但付费商品如何跳转支付结账流程不明确。

**修复方案**：

```javascript
// CatalogDetailView.vue — 修改购买按钮逻辑

async function handlePurchase() {
  const item = catalogDetail.value

  // 免费商品：直接购买
  if (item.price === 0) {
    await api.buyItem(item.id)
    showToast('获取成功')
    return
  }

  // 付费商品：跳转支付结账
  if (item.type === 'employee_pack') {
    // 员工包：跳转套餐选择
    router.push({
      path: '/plans',
      query: { item_id: item.id, subject: item.name, amount: item.price }
    })
  } else {
    // 其他商品：直接跳转结账
    router.push({
      path: `/checkout/new`,
      query: { item_id: item.id, subject: item.name, amount: item.price }
    })
  }
}
```

**后端支持**：确保 `payment_api.py` 的 `/api/payment/checkout` 接口支持 `order_kind="item"` 类型，并正确发放商品权益。

---

### 3.3 忘记密码 / 密码重置

**严重程度**：🟠 严重 — 用户忘记密码无法自助恢复

**涉及文件**：
- `modstore_server/auth_service.py`（后端）
- `market/src/router/index.js`（前端路由）
- 新增 `market/src/views/ForgotPasswordView.vue`

**修复方案**：

**步骤 1：后端添加密码重置接口**

```python
# auth_service.py — 新增密码重置

@router.post("/auth/forgot-password", summary="发送密码重置验证码")
async def forgot_password(body: ForgotPasswordBody, db: Session = Depends(get_db)):
    """发送密码重置验证码到邮箱。"""
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        # 安全考虑：不暴露邮箱是否存在
        return {"ok": True, "message": "如果该邮箱已注册，将收到验证码"}

    code = _generate_verification_code()
    _store_code(f"reset:{body.email}", code, expire_seconds=600)

    # 发送邮件
    from modstore_server.email_service import send_email
    try:
        send_email(
            to=body.email,
            subject="MODstore 密码重置",
            body=f"您的密码重置验证码为：{code}，10 分钟内有效。",
        )
    except Exception as e:
        logger.error("密码重置邮件发送失败: %s", e)

    return {"ok": True}


@router.post("/auth/reset-password", summary="重置密码")
async def reset_password(body: ResetPasswordBody, db: Session = Depends(get_db)):
    """使用验证码重置密码。"""
    stored_code = _get_stored_code(f"reset:{body.email}")
    if not stored_code or stored_code != body.code:
        raise HTTPException(400, "验证码无效或已过期")

    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    user.password_hash = _hash_password(body.new_password)
    _delete_code(f"reset:{body.email}")
    db.commit()

    return {"ok": True}


class ForgotPasswordBody(BaseModel):
    email: str

class ResetPasswordBody(BaseModel):
    email: str
    code: str
    new_password: str = Field(..., min_length=6)
```

**步骤 2：前端新增忘记密码页面**

```vue
<!-- ForgotPasswordView.vue -->
<template>
  <div class="forgot-password-page">
    <h2>忘记密码</h2>
    <div v-if="step === 1">
      <input v-model="email" type="email" placeholder="注册邮箱" />
      <button @click="sendCode" :disabled="countdown > 0">
        {{ countdown > 0 ? `${countdown}s 后重试` : '发送验证码' }}
      </button>
    </div>
    <div v-if="step === 2">
      <input v-model="code" placeholder="验证码" />
      <input v-model="newPassword" type="password" placeholder="新密码（至少6位）" />
      <input v-model="confirmPassword" type="password" placeholder="确认新密码" />
      <button @click="resetPassword" :disabled="!canReset">重置密码</button>
    </div>
    <router-link to="/login">返回登录</router-link>
  </div>
</template>
```

**步骤 3：路由注册**

```javascript
// router/index.js — 新增路由
{
  path: '/forgot-password',
  name: 'forgot-password',
  component: () => import('../views/ForgotPasswordView.vue'),
  meta: { guest: true }
}
```

---

### 3.4 Token 刷新机制

**严重程度**：🟠 严重 — JWT 过期后用户被强制登出

**涉及文件**：
- `modstore_server/auth_service.py`（后端）
- `market/src/api.js`（前端）

**修复方案**：

**步骤 1：后端支持 Token 刷新**

```python
# auth_service.py — 新增刷新接口

@router.post("/auth/refresh", summary="刷新访问令牌")
async def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """使用当前有效/即将过期的 token 换取新 token。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "缺少认证令牌")

    token = auth_header[7:]
    try:
        payload = jwt.decode(
            token,
            os.environ.get("JWT_SECRET", "dev-secret"),
            algorithms=["HS256"],
            options={"verify_exp": False},  # 允许过期 token 刷新
        )

        # 检查是否在刷新窗口内（过期后 24 小时内可刷新）
        exp = payload.get("exp", 0)
        if time.time() - exp > 86400:
            raise HTTPException(401, "刷新窗口已过期，请重新登录")

        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if not user:
            raise HTTPException(401, "用户不存在")

        new_token = _generate_jwt(user)
        return {"access_token": new_token, "token_type": "bearer"}

    except jwt.InvalidTokenError:
        raise HTTPException(401, "无效的认证令牌")
```

**步骤 2：前端自动刷新**

```javascript
// api.js — 添加自动刷新逻辑

let isRefreshing = false
let refreshSubscribers = []

function subscribeTokenRefresh(cb) {
  refreshSubscribers.push(cb)
}

function onTokenRefreshed(newToken) {
  refreshSubscribers.forEach(cb => cb(newToken))
  refreshSubscribers = []
}

async function fetchWithAuth(url, options = {}) {
  const token = localStorage.getItem('modstore_token')
  if (token) {
    options.headers = {
      ...options.headers,
      'Authorization': `Bearer ${token}`,
    }
  }

  let response = await fetch(url, options)

  if (response.status === 401 && token) {
    if (!isRefreshing) {
      isRefreshing = true
      try {
        const refreshRes = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
        })
        if (refreshRes.ok) {
          const data = await refreshRes.json()
          localStorage.setItem('modstore_token', data.access_token)
          onTokenRefreshed(data.access_token)
          isRefreshing = false
          // 重试原请求
          options.headers['Authorization'] = `Bearer ${data.access_token}`
          return fetch(url, options)
        }
      } catch (e) {
        // 刷新失败，清除 token
        localStorage.removeItem('modstore_token')
        window.location.href = '/login'
        return
      }
      isRefreshing = false
    }

    // 等待刷新完成
    return new Promise(resolve => {
      subscribeTokenRefresh(newToken => {
        options.headers['Authorization'] = `Bearer ${newToken}`
        resolve(fetch(url, options))
      })
    })
  }

  return response
}
```

---

### 3.5 钱包并发安全

**严重程度**：🟠 严重 — 并发场景下双花风险

**涉及文件**：`modstore_server/payment_api.py`（Python 后端钱包操作）

**修复方案**：

```python
# payment_api.py — 钱包操作添加行级锁

from sqlalchemy import orm

def wallet_add_balance(user_id: int, amount: float, db_session, description: str = ""):
    """充值（行级锁保障并发安全）。"""
    wallet = db_session.query(Wallet).filter(
        Wallet.user_id == user_id,
    ).with_for_update().first()  # SELECT ... FOR UPDATE

    if not wallet:
        wallet = Wallet(user_id=user_id, balance=0.0)
        db_session.add(wallet)
        db_session.flush()

    wallet.balance += amount

    transaction = Transaction(
        wallet_id=wallet.id,
        user_id=user_id,
        amount=amount,
        txn_type="credit",
        status="completed",
        description=description,
    )
    db_session.add(transaction)
    db_session.commit()


def wallet_deduct_balance(user_id: int, amount: float, db_session, description: str = ""):
    """扣款（行级锁保障并发安全）。"""
    wallet = db_session.query(Wallet).filter(
        Wallet.user_id == user_id,
    ).with_for_update().first()

    if not wallet:
        raise ValueError("钱包不存在")
    if wallet.balance < amount:
        raise ValueError(f"余额不足: 当前 {wallet.balance}, 需要 {amount}")

    wallet.balance -= amount

    transaction = Transaction(
        wallet_id=wallet.id,
        user_id=user_id,
        amount=-amount,
        txn_type="debit",
        status="completed",
        description=description,
    )
    db_session.add(transaction)
    db_session.commit()
```

---

### 3.6 404 页面

**严重程度**：🟠 严重 — 访问不存在路径显示空白

**涉及文件**：`market/src/router/index.js`

**修复方案**：

```javascript
// router/index.js — 添加通配路由

{
  path: '/:pathMatch(.*)*',
  name: 'not-found',
  component: () => import('../views/NotFoundView.vue'),
  meta: { title: '页面未找到' }
}
```

新增 `NotFoundView.vue`：

```vue
<template>
  <div class="not-found-page">
    <div class="not-found-content">
      <h1>404</h1>
      <p>抱歉，您访问的页面不存在</p>
      <router-link to="/" class="btn-home">返回首页</router-link>
    </div>
  </div>
</template>

<style scoped>
.not-found-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80vh;
  text-align: center;
}
.not-found-page h1 {
  font-size: 6rem;
  color: var(--accent);
  margin: 0;
}
.not-found-page p {
  font-size: 1.2rem;
  color: var(--text-secondary);
  margin: 1rem 0 2rem;
}
.btn-home {
  padding: 0.75rem 2rem;
  background: var(--accent);
  color: #fff;
  border-radius: 8px;
  text-decoration: none;
}
</style>
```

---

### 3.7 订单列表页

**严重程度**：🟠 中高 — 有 API 接口但无独立页面

**涉及文件**：新增 `market/src/views/OrderListView.vue`

**修复方案**：

```vue
<!-- OrderListView.vue -->
<template>
  <div class="order-list-page">
    <h2>我的订单</h2>
    <div class="order-filters">
      <button
        v-for="f in filters" :key="f.value"
        :class="{ active: currentFilter === f.value }"
        @click="currentFilter = f.value"
      >{{ f.label }}</button>
    </div>
    <div class="order-list">
      <div v-for="order in orders" :key="order.order_no" class="order-card" @click="goDetail(order)">
        <div class="order-header">
          <span class="order-no">{{ order.order_no }}</span>
          <span :class="['order-status', order.status]">{{ statusText(order.status) }}</span>
        </div>
        <div class="order-body">
          <span class="order-subject">{{ order.subject }}</span>
          <span class="order-amount">¥{{ order.total_amount }}</span>
        </div>
        <div class="order-footer">
          <span class="order-time">{{ formatTime(order.created_at) }}</span>
          <button v-if="order.status === 'paid'" class="btn-refund" @click.stop="goRefund(order)">申请退款</button>
        </div>
      </div>
    </div>
    <div v-if="!orders.length" class="empty-state">暂无订单</div>
  </div>
</template>
```

路由注册：

```javascript
{
  path: '/orders',
  name: 'orders',
  component: () => import('../views/OrderListView.vue'),
  meta: { auth: true }
}
```

---

## 四、P2 修复：运营与体验优化

### 4.1 AI 员工执行深度补全

**涉及文件**：`modstore_server/employee_executor.py`

#### 4.1.1 Excel 解析（openpyxl）

```python
# employee_executor.py — 替换 Excel 占位实现

def _perception_excel(input_data):
    """Excel 解析：使用 openpyxl 读取 .xlsx 文件。"""
    import openpyxl
    import io
    import base64

    raw = input_data
    if isinstance(input_data, dict):
        raw = input_data.get("content", input_data.get("base64", ""))

    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]

    try:
        wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(raw)), read_only=True)
        sheets_data = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append([str(c) if c is not None else "" for c in row])
            sheets_data[sheet_name] = {
                "rows": rows,
                "row_count": len(rows),
                "col_count": len(rows[0]) if rows else 0,
            }
        wb.close()
        return {"normalized_input": sheets_data, "type": "excel", "parse_ok": True}
    except Exception as e:
        return {"normalized_input": input_data, "type": "excel", "parse_error": str(e)}
```

#### 4.1.2 OCR / 图片解析（Vision Model）

```python
# employee_executor.py — 替换 image 占位实现

def _perception_image(input_data, user_id, session):
    """图片解析：优先使用 LLM Vision，回退到 OCR。"""
    import base64

    raw = input_data
    if isinstance(input_data, dict):
        raw = input_data.get("base64", input_data.get("url", ""))

    # 尝试使用 LLM Vision
    from modstore_server.llm_key_resolver import resolve_api_key
    api_key, source = resolve_api_key(session, user_id, "openai")

    if api_key:
        try:
            from modstore_server.llm_chat_proxy import chat_dispatch
            import asyncio

            image_content = raw
            if isinstance(raw, str) and not raw.startswith("data:"):
                image_content = f"data:image/png;base64,{raw}"

            result = asyncio.run(chat_dispatch(
                "openai",
                api_key=api_key,
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请描述这张图片的内容，提取其中的文字信息。"},
                        {"type": "image_url", "image_url": {"url": image_content}},
                    ],
                }],
                max_tokens=1000,
            ))

            if result.get("ok"):
                return {
                    "normalized_input": {"description": result["content"], "type": "image"},
                    "type": "image",
                    "parse_ok": True,
                    "method": "vision",
                }
        except Exception:
            pass

    return {
        "normalized_input": input_data,
        "type": "image",
        "note": "图片解析需要配置 OpenAI API Key（支持 Vision 模型）",
    }
```

#### 4.1.3 长期记忆 / 知识库（向量数据库）

```python
# employee_executor.py — 替换长期记忆占位实现

def _memory_long_term(employee_id: str, query: str, user_id: int, session):
    """长期记忆：使用 ChromaDB 向量检索。"""
    try:
        import chromadb

        client = chromadb.PersistentClient(path="./data/chroma")
        collection = client.get_or_create_collection(
            name=f"employee_{employee_id}",
            metadata={"hnsw:space": "cosine"},
        )

        results = collection.query(
            query_texts=[query],
            n_results=5,
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        memories = []
        for doc, dist in zip(documents, distances):
            if dist < 0.8:  # 相似度阈值
                memories.append({"content": doc, "distance": dist})

        return {"memories": memories, "count": len(memories)}

    except ImportError:
        return {"memories": [], "note": "需要安装 chromadb: pip install chromadb"}
    except Exception as e:
        return {"memories": [], "error": str(e)}
```

#### 4.1.4 微信通知真实集成

```python
# employee_executor.py — 替换 wechat_notify 占位实现

def _action_wechat_notify(config: dict, reasoning: dict, task: str):
    """微信通知：通过企业微信 Webhook 发送。"""
    wechat_cfg = config.get("wechat_notify", {})
    webhook_url = wechat_cfg.get("webhook_url", "")

    if not webhook_url:
        return {"handler": "wechat_notify", "status": "not_configured", "message": "未配置企业微信 Webhook URL"}

    import httpx

    message_type = wechat_cfg.get("message_type", "text")
    content = reasoning.get("reasoning", "")[:2048]

    payload = {
        "msgtype": message_type,
        message_type: {
            "content": f"【AI员工通知】\n任务: {task}\n结果: {content}",
        },
    }

    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200 and resp.json().get("errcode") == 0:
            return {"handler": "wechat_notify", "status": "ok"}
        else:
            return {"handler": "wechat_notify", "status": "failed", "response": resp.text[:500]}
    except Exception as e:
        return {"handler": "wechat_notify", "status": "error", "error": str(e)}
```

---

### 4.2 通知系统增强

**涉及文件**：
- `market/src/views/NotificationCenter.vue`（前端）
- `market/src/App.vue`（前端）

#### 4.2.1 未读数量角标

```vue
<!-- App.vue — 导航栏添加通知角标 -->
<template>
  <nav>
    <!-- ... 其他导航项 ... -->
    <router-link to="/notifications" class="nav-notification">
      <span class="icon-bell">🔔</span>
      <span v-if="unreadCount > 0" class="badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
    </router-link>
  </nav>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from './api.js'

const unreadCount = ref(0)
let pollTimer = null

async function fetchUnreadCount() {
  try {
    const res = await api.notificationsList(true, 1)
    if (res.ok) {
      unreadCount.value = res.data.unread_count || 0
    }
  } catch {}
}

onMounted(() => {
  fetchUnreadCount()
  pollTimer = setInterval(fetchUnreadCount, 30000) // 30秒轮询
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.nav-notification {
  position: relative;
}
.badge {
  position: absolute;
  top: -6px;
  right: -8px;
  background: #ef4444;
  color: #fff;
  font-size: 0.7rem;
  padding: 1px 5px;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}
</style>
```

#### 4.2.2 通知分类筛选

```vue
<!-- NotificationCenter.vue — 添加分类筛选 -->
<template>
  <div class="notification-filters">
    <button
      v-for="cat in categories" :key="cat.value"
      :class="{ active: currentCategory === cat.value }"
      @click="currentCategory = cat.value"
    >{{ cat.label }}</button>
  </div>
</template>

<script setup>
const categories = [
  { value: 'all', label: '全部' },
  { value: 'payment_success', label: '支付' },
  { value: 'employee_execution_done', label: '员工' },
  { value: 'quota_warning', label: '配额' },
  { value: 'system', label: '系统' },
]
</script>
```

#### 4.2.3 通知点击跳转

```javascript
// NotificationCenter.vue — 点击通知跳转到相关资源

function handleNotificationClick(notification) {
  // 标记已读
  api.notificationMarkRead(notification.id)

  // 根据类型跳转
  const data = JSON.parse(notification.data_json || '{}')
  switch (notification.type) {
    case 'payment_success':
      router.push(`/order/${data.order_no}`)
      break
    case 'employee_execution_done':
      router.push(`/workbench?focus=employee`)
      break
    case 'quota_warning':
      router.push('/wallet')
      break
  }
}
```

---

### 4.3 订单管理完善

**涉及文件**：
- `modstore_server/payment_api.py`（后端）

#### 4.3.1 订单取消接口

```python
# payment_api.py — 新增取消订单

@router.post("/cancel/{order_no}", summary="取消订单")
async def cancel_order(
    order_no: str,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    order = db.query(Order).filter(
        Order.order_no == order_no,
        Order.user_id == user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "pending":
        raise HTTPException(400, f"订单状态为 {order.status}，无法取消")

    order.status = "closed"
    db.commit()
    return {"ok": True}
```

#### 4.3.2 订单超时自动关闭

```python
# payment_api.py — 添加定时任务（或放在独立的 scheduler 中）

from apscheduler.schedulers.background import BackgroundScheduler

def close_expired_orders():
    """关闭超过 30 分钟未支付的订单。"""
    from datetime import timedelta
    sf = get_session_factory()
    with sf() as session:
        threshold = datetime.utcnow() - timedelta(minutes=30)
        expired = session.query(Order).filter(
            Order.status == "pending",
            Order.created_at < threshold,
        ).all()
        for order in expired:
            order.status = "closed"
        session.commit()
        if expired:
            logger.info("已关闭 %d 个超时订单", len(expired))

# 在 app.py 启动时注册
scheduler = BackgroundScheduler()
scheduler.add_job(close_expired_orders, 'interval', minutes=5)
scheduler.start()
```

#### 4.3.3 支付超时后重新支付

```vue
<!-- PaymentCheckoutView.vue — 添加重新支付按钮 -->
<template>
  <div v-if="orderExpired" class="expired-actions">
    <p>支付超时，订单已关闭</p>
    <button @click="retryPayment" class="btn-retry">重新支付</button>
  </div>
</template>

<script setup>
function retryPayment() {
  router.push({
    path: '/plans',
    query: {
      item_id: route.query.item_id,
      subject: route.query.subject,
      amount: route.query.amount,
    }
  })
}
</script>
```

---

### 4.4 工作流编辑器修复

**涉及文件**：`market/src/views/WorkflowView.vue`

#### 4.4.1 连线交互补全

```javascript
// WorkflowView.vue — 补全连线交互

let connectingFrom = null
let tempLine = null

function startConnect(nodeId, event) {
  connectingFrom = nodeId
  const svg = document.querySelector('.workflow-canvas svg')
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  const svgP = point.matrixTransform(svg.getScreenCTM().inverse())

  tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'line')
  tempLine.setAttribute('x1', svgP.x)
  tempLine.setAttribute('y1', svgP.y)
  tempLine.setAttribute('x2', svgP.x)
  tempLine.setAttribute('y2', svgP.y)
  tempLine.setAttribute('stroke', '#6366f1')
  tempLine.setAttribute('stroke-width', '2')
  tempLine.setAttribute('stroke-dasharray', '5,5')
  svg.appendChild(tempLine)
}

function onMouseMove(event) {
  if (!connectingFrom || !tempLine) return
  const svg = document.querySelector('.workflow-canvas svg')
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  const svgP = point.matrixTransform(svg.getScreenCTM().inverse())
  tempLine.setAttribute('x2', svgP.x)
  tempLine.setAttribute('y2', svgP.y)
}

function endConnect(targetNodeId) {
  if (!connectingFrom || connectingFrom === targetNodeId) {
    cancelConnect()
    return
  }

  // 创建边
  createEdge({
    source: connectingFrom,
    target: targetNodeId,
  })

  cancelConnect()
}

function cancelConnect() {
  connectingFrom = null
  if (tempLine) {
    tempLine.remove()
    tempLine = null
  }
}
```

#### 4.4.2 工作流保存策略优化

```javascript
// WorkflowView.vue — 改为先增删改再保存

async function saveWorkflow() {
  const currentNodes = /* 当前画布节点 */
  const currentEdges = /* 当前画布边 */

  // 增量更新：只发送变化的部分
  const addedNodes = currentNodes.filter(n => !n.persisted)
  const removedNodes = persistedNodeIds.filter(id => !currentNodes.find(n => n.id === id))
  const addedEdges = currentEdges.filter(e => !e.persisted)
  const removedEdges = persistedEdgeIds.filter(id => !currentEdges.find(e => e.id === id))

  // 依次执行增删
  for (const node of addedNodes) {
    await api.createWorkflowNode(workflowId, node)
  }
  for (const nodeId of removedNodes) {
    await api.deleteWorkflowNode(workflowId, nodeId)
  }
  for (const edge of addedEdges) {
    await api.createWorkflowEdge(workflowId, edge)
  }
  for (const edgeId of removedEdges) {
    await api.deleteWorkflowEdge(workflowId, edgeId)
  }
}
```

---

### 4.5 员工制作向导与 BlockBuilder 统一

**涉及文件**：
- `market/src/views/EmployeeAuthoringView.vue`
- `market/src/views/employee-steps/Step1Identity.vue` ~ `Step7Management.vue`

**修复方案**：

在 `EmployeeAuthoringView.vue` 中添加模式切换说明：

```vue
<!-- EmployeeAuthoringView.vue — 添加模式切换提示 -->
<template>
  <div class="authoring-mode-switch">
    <div class="mode-info">
      <span v-if="currentMode === 'wizard'" class="mode-badge">简化向导</span>
      <span v-else class="mode-badge advanced">高级构建器</span>
      <button @click="toggleMode" class="btn-toggle">
        切换到{{ currentMode === 'wizard' ? '高级构建器' : '简化向导' }}
      </button>
    </div>
    <p class="mode-hint">
      {{ currentMode === 'wizard'
        ? '简化向导：通过开关快速配置员工各层能力'
        : '高级构建器：通过拖拽画布和 JSON 编辑精确控制员工行为' }}
    </p>
  </div>
</template>
```

Step0 模板选择后自动预填充：

```javascript
// EmployeeAuthoringView.vue — 模板选择后预填充

function onTemplateSelected(template) {
  const presets = {
    simple_workflow: {
      identity: { name: '简单工作流员工' },
      perception: { type: 'json', enabled: true },
      memory: { short_term: { enabled: true } },
      cognition: { agent: { system_prompt: '你是一个工作流执行助手' } },
      actions: { handlers: ['echo', 'webhook'] },
    },
    dialog_agent: {
      identity: { name: '对话型 Agent' },
      perception: { type: 'text', enabled: true },
      memory: { short_term: { enabled: true }, long_term: { enabled: true } },
      cognition: { agent: { system_prompt: '你是一个智能对话助手，请根据用户需求提供帮助' } },
      actions: { handlers: ['echo'] },
    },
    phone_service: {
      identity: { name: '电话客服员工' },
      perception: { type: 'json', enabled: true },
      memory: { short_term: { enabled: true } },
      cognition: { agent: { system_prompt: '你是一个电话客服，请礼貌专业地回答客户问题' } },
      actions: { handlers: ['echo', 'http_request'] },
      collaboration: { workflow: { enabled: true } },
    },
    data_processor: {
      identity: { name: '数据处理员工' },
      perception: { type: 'csv', enabled: true },
      memory: { short_term: { enabled: true } },
      cognition: { agent: { system_prompt: '你是一个数据处理助手，请分析提供的数据并生成报告' } },
      actions: { handlers: ['echo', 'data_sync'] },
    },
    all_round: {
      identity: { name: '全能型员工' },
      perception: { type: 'json', enabled: true },
      memory: { short_term: { enabled: true }, long_term: { enabled: true } },
      cognition: { agent: { system_prompt: '你是一个全能型 AI 员工，能够处理各种任务' } },
      actions: { handlers: ['echo', 'http_request', 'webhook', 'data_sync'] },
      collaboration: { workflow: { enabled: true } },
      management: { scheduler: { enabled: true } },
    },
  }

  const preset = presets[template]
  if (preset) {
    employeeConfig.value = { ...employeeConfig.value, ...preset }
  }
}
```

---

## 五、P3 修复：扩展与部署

### 5.1 门户网站内容完善

**涉及文件**：
- `contact.html`（联系表单后端对接）
- `about.html` / `services.html` / `cases.html`（内容真实性）

#### 5.1.1 联系表单后端对接

```python
# app.py — 新增联系表单提交接口

@app.route("/api/contact", methods=["POST"])
def submit_contact():
    """门户网站联系表单提交。"""
    data = request.json or {}
    name = data.get("name", "").strip()
    company = data.get("company", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()

    if not name or not email or not message:
        return {"ok": False, "error": "请填写必填项"}, 400

    # 发送邮件通知
    from modstore_server.email_service import send_email
    try:
        send_email(
            to=os.environ.get("CONTACT_EMAIL", "admin@xiu-ci.com"),
            subject=f"新客户咨询 - {name}（{company or '未填写公司'}）",
            body=f"姓名: {name}\n公司: {company}\n邮箱: {email}\n电话: {phone}\n\n需求:\n{message}",
        )
    except Exception as e:
        logger.error("联系表单邮件发送失败: %s", e)

    return {"ok": True, "message": "感谢您的咨询，我们将尽快与您联系！"}
```

```javascript
// contact.html — 修改表单提交逻辑

form.addEventListener('submit', async (e) => {
  e.preventDefault()
  const formData = new FormData(form)
  const data = Object.fromEntries(formData.entries())

  try {
    const res = await fetch('/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    const result = await res.json()
    if (result.ok) {
      showToast(result.message)
      form.reset()
    } else {
      showToast(result.error || '提交失败，请稍后重试')
    }
  } catch {
    showToast('网络错误，请稍后重试')
  }
})
```

#### 5.1.2 内容真实性完善

- 移除所有"规划中"、"示例"标注，替换为实际内容或删除对应区块
- 填写公司地址和商务联系人
- 添加 XCAGI 系统实际截图
- 新闻条目使用真实发布内容

---

### 5.2 公网部署基础设施

**涉及文件**：`nginx-xiu-ci.conf`、`.env.production`

#### 5.2.1 HTTPS 配置

```nginx
# nginx-xiu-ci.conf — 添加 HTTPS

server {
    listen 443 ssl http2;
    server_name xiu-ci.com www.xiu-ci.com;

    ssl_certificate /etc/nginx/ssl/xiu-ci.com_bundle.crt;
    ssl_certificate_key /etc/nginx/ssl/xiu-ci.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # MODstore 前端
    location / {
        root /var/www/modstore/dist;
        try_files $uri $uri/ /index.html;
    }

    # MODstore API
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 支付宝回调（必须 HTTPS）
    location /api/payment/notify/ {
        proxy_pass http://127.0.0.1:5000;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:5000;
    }
}

server {
    listen 80;
    server_name xiu-ci.com www.xiu-ci.com;
    return 301 https://$host$request_uri;
}
```

#### 5.2.2 生产环境变量

```bash
# .env.production — 关键配置

JWT_SECRET=<生成一个强随机密钥>
PAYMENT_SECRET_KEY=<生成一个强随机密钥>
ALIPAY_APP_ID=<正式环境 App ID>
ALIPAY_PRIVATE_KEY=<正式环境私钥>
ALIPAY_PUBLIC_KEY=<正式环境公钥>
ALIPAY_NOTIFY_URL=https://xiu-ci.com/api/payment/notify/alipay
CONTACT_EMAIL=business@xiu-ci.com
MODSTORE_VERSION=1.0.0
```

#### 5.2.3 数据库迁移（SQLite → PostgreSQL）

```python
# migrate_sqlite_to_pg.py — 数据库迁移脚本

"""将 SQLite 数据迁移到 PostgreSQL。"""
import sqlite3
import psycopg2
import os

def migrate():
    sqlite_path = os.environ.get("SQLITE_PATH", "./modstore.db")
    pg_url = os.environ.get("DATABASE_URL")

    if not pg_url:
        print("请设置 DATABASE_URL 环境变量")
        return

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(pg_url)

    tables = [
        "users", "orders", "wallets", "transactions",
        "catalog_items", "entitlements", "user_plans", "quotas",
        "notifications", "refund_requests", "workflow_triggers",
        "employee_execution_metrics",
    ]

    for table in tables:
        try:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0 rows, skipped")
                continue

            cols = rows[0].keys()
            placeholders = ", ".join(["%s"] * len(cols))
            col_names = ", ".join(cols)

            cur = pg_conn.cursor()
            for row in rows:
                values = tuple(row[c] for c in cols)
                cur.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
                    f"ON CONFLICT DO NOTHING",
                    values,
                )
            pg_conn.commit()
            print(f"  {table}: {len(rows)} rows migrated")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")
            pg_conn.rollback()

    sqlite_conn.close()
    pg_conn.close()
    print("迁移完成")

if __name__ == "__main__":
    migrate()
```

---

### 5.3 商品运营功能

**涉及文件**：新增后端接口和前端组件

#### 5.3.1 商品评价系统

```python
# catalog_api.py — 新增评价接口

@router.post("/{catalog_id}/review", summary="提交商品评价")
async def submit_review(
    catalog_id: int,
    body: ReviewBody,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    # 检查是否购买
    entitlement = db.query(Entitlement).filter(
        Entitlement.user_id == user.id,
        Entitlement.catalog_id == catalog_id,
    ).first()
    if not entitlement:
        raise HTTPException(403, "购买后才能评价")

    # 检查是否已评价
    existing = db.query(Review).filter(
        Review.user_id == user.id,
        Review.catalog_id == catalog_id,
    ).first()
    if existing:
        raise HTTPException(400, "已评价过")

    review = Review(
        user_id=user.id,
        catalog_id=catalog_id,
        rating=body.rating,
        content=body.content,
    )
    db.add(review)
    db.commit()
    return {"ok": True}


@router.get("/{catalog_id}/reviews", summary="获取商品评价")
async def get_reviews(catalog_id: int, db: Session = Depends(get_db)):
    reviews = db.query(Review).filter(
        Review.catalog_id == catalog_id,
    ).order_by(Review.created_at.desc()).limit(50).all()
    return {
        "reviews": [
            {
                "id": r.id,
                "user_name": r.user.username if r.user else "匿名",
                "rating": r.rating,
                "content": r.content,
                "created_at": r.created_at.isoformat(),
            }
            for r in reviews
        ],
        "average_rating": sum(r.rating for r in reviews) / len(reviews) if reviews else 0,
        "total": len(reviews),
    }
```

#### 5.3.2 收藏功能

```python
# catalog_api.py — 新增收藏接口

@router.post("/{catalog_id}/favorite", summary="收藏/取消收藏")
async def toggle_favorite(
    catalog_id: int,
    db: Session = Depends(get_db),
    user = Depends(_get_current_user),
):
    existing = db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.catalog_id == catalog_id,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"ok": True, "favorited": False}
    else:
        db.add(Favorite(user_id=user.id, catalog_id=catalog_id))
        db.commit()
        return {"ok": True, "favorited": True}
```

---

### 5.4 用户账户管理

**涉及文件**：新增 `market/src/views/AccountSettingsView.vue`

```vue
<!-- AccountSettingsView.vue -->
<template>
  <div class="account-settings">
    <h2>账户设置</h2>

    <section class="profile-section">
      <h3>基本信息</h3>
      <div class="form-group">
        <label>用户名</label>
        <input v-model="form.username" :disabled="saving" />
      </div>
      <div class="form-group">
        <label>邮箱</label>
        <input v-model="form.email" type="email" disabled />
        <span class="hint">邮箱修改请联系客服</span>
      </div>
      <button @click="saveProfile" :disabled="saving">保存</button>
    </section>

    <section class="password-section">
      <h3>修改密码</h3>
      <div class="form-group">
        <label>当前密码</label>
        <input v-model="passwordForm.current" type="password" />
      </div>
      <div class="form-group">
        <label>新密码</label>
        <input v-model="passwordForm.new_pass" type="password" />
      </div>
      <div class="form-group">
        <label>确认新密码</label>
        <input v-model="passwordForm.confirm" type="password" />
      </div>
      <button @click="changePassword" :disabled="!canChangePassword">修改密码</button>
    </section>

    <section class="danger-section">
      <h3>危险操作</h3>
      <button class="btn-danger" @click="confirmDeleteAccount">注销账户</button>
    </section>
  </div>
</template>
```

路由注册：

```javascript
{
  path: '/account',
  name: 'account',
  component: () => import('../views/AccountSettingsView.vue'),
  meta: { auth: true }
}
```

---

### 5.5 微信电话业务员专用工作流

**涉及文件**：`modstore_server/workflow_employee_scaffold.py`

```python
# workflow_employee_scaffold.py — 新增微信电话业务员专用模板

PHONE_WECHAT_SCAFFOLD = {
    "name": "微信电话业务员",
    "description": "自动处理微信和电话客户咨询",
    "nodes": [
        {"id": "start", "type": "trigger", "label": "客户来电/消息", "config": {"trigger_type": "webhook"}},
        {"id": "intent", "type": "employee", "label": "意图识别", "config": {
            "employee_id": "",  # 动态填充
            "task": "识别客户意图",
            "system_prompt": "请判断客户意图：咨询/投诉/购买/售后/其他",
        }},
        {"id": "branch", "type": "condition", "label": "意图分支", "config": {
            "field": "intent",
            "branches": {
                "咨询": "answer",
                "投诉": "escalate",
                "购买": "sales",
                "售后": "support",
                "default": "answer",
            }
        }},
        {"id": "answer", "type": "employee", "label": "智能回答", "config": {
            "task": "回答客户问题",
        }},
        {"id": "escalate", "type": "action", "label": "转人工", "config": {
            "handler": "wechat_notify",
            "message": "客户投诉，请人工介入",
        }},
        {"id": "sales", "type": "employee", "label": "销售引导", "config": {
            "task": "推荐产品",
            "system_prompt": "你是销售顾问，根据客户需求推荐合适的产品",
        }},
        {"id": "support", "type": "employee", "label": "售后处理", "config": {
            "task": "处理售后问题",
        }},
    ],
    "edges": [
        {"source": "start", "target": "intent"},
        {"source": "intent", "target": "branch"},
        {"source": "branch", "target": "answer", "condition": "咨询"},
        {"source": "branch", "target": "escalate", "condition": "投诉"},
        {"source": "branch", "target": "sales", "condition": "购买"},
        {"source": "branch", "target": "support", "condition": "售后"},
        {"source": "branch", "target": "answer", "condition": "default"},
    ],
}
```

---

## 六、数据库迁移 SQL

### 6.1 新增表

```sql
-- 商品评价表
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    catalog_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    content TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, catalog_id)
);
CREATE INDEX IF NOT EXISTS idx_reviews_catalog_id ON reviews(catalog_id);

-- 收藏表
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    catalog_id INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, catalog_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id);

-- 密码重置验证码表（如果使用数据库存储而非内存）
-- 注意：当前验证码存储在内存中，生产环境建议使用 Redis
```

### 6.2 现有表字段补充

```sql
-- 退款申请表添加管理员审核字段（如果缺失）
ALTER TABLE refund_requests ADD COLUMN admin_note TEXT DEFAULT '';
ALTER TABLE refund_requests ADD COLUMN reviewed_at DATETIME;
ALTER TABLE refund_requests ADD COLUMN reviewed_by INTEGER;

-- 订单表添加 fulfilled 字段（如果缺失）
ALTER TABLE orders ADD COLUMN fulfilled BOOLEAN DEFAULT 0;

-- 用户表添加 last_login 字段
ALTER TABLE users ADD COLUMN last_login DATETIME;
```

---

## 七、前端修复清单

### 7.1 新增页面

| 文件 | 说明 | 优先级 |
|------|------|--------|
| `views/NotFoundView.vue` | 404 页面 | P1 |
| `views/ForgotPasswordView.vue` | 忘记密码 | P1 |
| `views/OrderListView.vue` | 订单列表 | P1 |
| `views/AccountSettingsView.vue` | 账户设置 | P3 |

### 7.2 修改现有页面

| 文件 | 修改内容 | 优先级 |
|------|----------|--------|
| `api.js` | 移除前端签名逻辑，改为后端签名；添加 Token 自动刷新 | P0 |
| `App.vue` | 添加通知角标、用户菜单（退出登录/账户设置） | P1 |
| `router/index.js` | 添加 404 路由、忘记密码路由、订单列表路由、账户设置路由 | P1 |
| `CatalogDetailView.vue` | 付费商品跳转支付结账流程；添加评价/收藏 | P1/P3 |
| `RefundApplyView.vue` | 从订单列表选择订单号；退款进度时间线；退款政策说明 | P1 |
| `NotificationCenter.vue` | 分类筛选；点击跳转；删除通知 | P2 |
| `PaymentCheckoutView.vue` | 支付超时后重新支付按钮 | P2 |
| `WorkflowView.vue` | 连线交互补全；保存策略优化 | P2 |
| `EmployeeAuthoringView.vue` | 模式切换说明；模板预填充 | P2 |
| `WalletView.vue` | 添加扣款 API 调用（购买商品时） | P1 |

### 7.3 API 封装新增

```javascript
// api.js — 新增接口

// 密码重置
sendResetCode: (email) => post('/api/auth/forgot-password', { email }),
resetPassword: (email, code, new_password) => post('/api/auth/reset-password', { email, code, new_password }),

// Token 刷新
refreshToken: () => post('/api/auth/refresh'),

// 支付签名（后端签名）
signCheckout: (params) => post('/api/payment/sign-checkout', params),

// 订单
cancelOrder: (orderNo) => post(`/api/payment/cancel/${orderNo}`),
orderList: (status) => get('/api/payment/orders', { status }),

// 评价
submitReview: (catalogId, rating, content) => post(`/api/catalog/${catalogId}/review`, { rating, content }),
getReviews: (catalogId) => get(`/api/catalog/${catalogId}/reviews`),

// 收藏
toggleFavorite: (catalogId) => post(`/api/catalog/${catalogId}/favorite`),

// 账户
updateProfile: (data) => put('/api/auth/profile', data),
changePassword: (current, new_pass) => post('/api/auth/change-password', { current_password: current, new_password: new_pass }),
```

---

## 八、依赖安装

```bash
# Python 后端新增依赖
pip install openpyxl chromadb

# 更新 requirements.txt
echo "openpyxl>=3.1.0" >> requirements.txt
echo "chromadb>=0.4.0" >> requirements.txt

# 注意：apscheduler 已在前序文档中添加
```

---

## 九、验证清单

### 9.1 P0 验证

- [ ] 支付宝通知金额校验：伪造金额不同的通知 → 返回"金额不匹配"
- [ ] 支付宝通知幂等性：重复发送同一通知 → 权益不重复发放
- [ ] 员工执行权限：未购买用户执行员工 → 返回 403
- [ ] 支付签名：前端无法获取签名密钥，所有签名由后端生成
- [ ] Catalog 数据一致性：数据库和 JSON 文件数据一致

### 9.2 P1 验证

- [ ] 退款管理员审核：管理员可查看/审批退款，审批后调用支付宝退款
- [ ] 购买→支付衔接：付费商品点击购买 → 跳转支付结账 → 支付成功 → 权益发放
- [ ] 忘记密码：输入邮箱 → 收到验证码 → 重置密码 → 新密码登录成功
- [ ] Token 刷新：JWT 过期后自动刷新，用户无感知
- [ ] 钱包并发：同时发起 10 笔充值/扣款 → 余额正确
- [ ] 404 页面：访问不存在的路径 → 显示 404 页面
- [ ] 订单列表：查看所有订单，按状态筛选

### 9.3 P2 验证

- [ ] Excel 解析：上传 .xlsx 文件 → 正确解析内容
- [ ] 图片解析：上传图片 → Vision Model 返回描述
- [ ] 通知角标：有未读通知时导航栏显示红色角标
- [ ] 通知跳转：点击支付通知 → 跳转订单详情
- [ ] 订单取消：取消待支付订单 → 状态变为 closed
- [ ] 订单超时：30 分钟未支付 → 自动关闭
- [ ] 工作流连线：拖拽连线 → 成功创建边
- [ ] 模板预填充：选择模板 → 后续步骤自动填充配置

### 9.4 P3 验证

- [ ] 联系表单：提交表单 → 收到邮件通知
- [ ] HTTPS：访问 http:// → 自动跳转 https://
- [ ] 商品评价：购买后可评价，评价显示在商品详情页
- [ ] 收藏：收藏/取消收藏功能正常
- [ ] 账户设置：修改用户名/密码成功
- [ ] 微信电话工作流：选择模板 → 自动生成 7 节点工作流

---

## 十、实施路线图

### 阶段一（2-3 天）：P0 安全与关键逻辑

| 序号 | 修复项 | 预估 |
|------|--------|------|
| 1 | 支付宝通知金额校验 + 幂等性 | 0.5 天 |
| 2 | 员工执行权限校验 | 0.5 天 |
| 3 | 前端支付签名移至后端 | 1 天 |
| 4 | Java 支付服务决策（弃用/修复） | 0.5 天 |
| 5 | Catalog 双存储同步 | 0.5 天 |

### 阶段二（3-4 天）：P1 核心体验

| 序号 | 修复项 | 预估 |
|------|--------|------|
| 6 | 退款管理员审核 + 支付宝退款接口 | 1 天 |
| 7 | 购买→支付结账流程衔接 | 0.5 天 |
| 8 | 忘记密码 + 密码重置 | 0.5 天 |
| 9 | Token 刷新机制 | 0.5 天 |
| 10 | 钱包并发安全 | 0.5 天 |
| 11 | 404 页面 + 订单列表页 | 0.5 天 |

### 阶段三（3-5 天）：P2 运营优化

| 序号 | 修复项 | 预估 |
|------|--------|------|
| 12 | Excel 解析（openpyxl） | 0.5 天 |
| 13 | OCR / 图片解析（Vision Model） | 1 天 |
| 14 | 长期记忆 / 知识库（ChromaDB） | 1 天 |
| 15 | 微信通知真实集成 | 0.5 天 |
| 16 | 通知系统增强（角标/分类/跳转） | 1 天 |
| 17 | 订单管理完善（取消/超时/重新支付） | 0.5 天 |
| 18 | 工作流编辑器修复（连线/保存） | 1 天 |
| 19 | 员工制作向导优化（模式切换/模板预填充） | 0.5 天 |

### 阶段四（3-5 天）：P3 扩展与部署

| 序号 | 修复项 | 预估 |
|------|--------|------|
| 20 | 门户网站联系表单后端 + 内容完善 | 1 天 |
| 21 | 公网部署（HTTPS/域名/生产密钥） | 1 天 |
| 22 | 数据库迁移（SQLite → PostgreSQL） | 1 天 |
| 23 | 商品运营功能（评价/收藏） | 1 天 |
| 24 | 用户账户管理 | 0.5 天 |
| 25 | 微信电话业务员工作流 | 0.5 天 |

**总计预估：11-17 天**

---

## 十一、风险与注意事项

### 11.1 安全风险

| 风险 | 缓解措施 |
|------|---------|
| 支付密钥泄露 | 签名逻辑移至后端，密钥不暴露给前端 |
| JWT 密钥弱 | 生产环境必须配置强随机密钥 |
| 金额篡改 | 通知处理时校验金额 |
| 并发双花 | 钱包操作使用行级锁 |

### 11.2 兼容性风险

| 风险 | 缓解措施 |
|------|---------|
| 前端签名移除后旧版本不兼容 | 部署时前后端同步更新 |
| 数据库迁移数据丢失 | 迁移前备份 SQLite 数据库 |
| ChromaDB 依赖冲突 | 使用独立虚拟环境或 Docker 隔离 |

### 11.3 运营风险

| 风险 | 缓解措施 |
|------|---------|
| LLM 调用成本增加 | 配额检查 + 用户 BYOK |
| 退款资金安全 | 管理员审核 + 退款时限控制 |
| 员工执行沙盒逃逸 | Docker 隔离 + 资源限制 |

### 11.4 向后兼容

- 保留 `mock_employees=True` 的沙盒模式
- 旧版 API 路由保持可用
- 前端旧链接（如 `/#ai-market`）继续重定向
