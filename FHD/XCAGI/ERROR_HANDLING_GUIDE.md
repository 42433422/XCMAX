# 统一错误处理机制使用指南

## 📋 概述

XCAGI 系统已实现统一的错误处理机制，提供标准化的异常类、错误响应格式和异常处理器。

---

## 🎯 核心组件

### 1. 异常类层次结构

```
AppException (基类)
├── ValidationError (验证错误 422)
├── NotFoundError (资源未找到 404)
├── AuthenticationError (认证失败 401)
├── AuthorizationError (授权失败 403)
├── BusinessError (业务错误 400)
├── DatabaseError (数据库错误 500)
├── ExternalServiceError (外部服务错误 503)
├── RateLimitError (频率限制 429)
└── NeuroError (Neuro 总线错误 500)
    ├── NeuroTimeoutError (超时 504)
    └── NeuroNotFoundError (未找到 404)
```

### 2. 统一响应格式

**成功响应**:
```json
{
  "success": true,
  "message": "操作成功",
  "data": {...}
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "错误信息",
  "code": "ERROR_CODE"
}
```

**验证错误响应**:
```json
{
  "success": false,
  "error": "请求参数验证失败",
  "code": "VALIDATION_ERROR",
  "details": [
    {
      "field": "body.customer_name",
      "message": "field required",
      "type": "missing"
    }
  ]
}
```

---

## 💻 使用方法

### 1. 抛出异常

```python
from app.exceptions import ValidationError, NotFoundError, BusinessError

# 验证错误
if not data.get("customer_name"):
    raise ValidationError("客户名称不能为空")

# 资源未找到
shipment = repo.find_by_id(shipment_id)
if not shipment:
    raise NotFoundError("发货单不存在")

# 业务错误
if quantity <= 0:
    raise BusinessError("数量必须大于 0", code="INVALID_QUANTITY")

# 认证错误
if not user:
    raise AuthenticationError("用户未登录")

# 授权错误
if user.role != "admin":
    raise AuthorizationError("需要管理员权限")
```

### 2. 在 FastAPI 路由中使用

```python
from fastapi import APIRouter
from app.exceptions import ValidationError, NotFoundError
from app.schemas.response import SuccessResponse, ErrorResponse

router = APIRouter()

@router.post("/generate")
async def generate_shipment(req: ShipmentGenerateRequest):
    """生成发货单"""
    # 验证通过 Pydantic 自动完成
    
    # 业务逻辑验证
    if not req.items:
        raise ValidationError("商品列表不能为空")
    
    # 处理逻辑
    result = await process_shipment(req)
    
    # 返回成功响应
    return SuccessResponse.create(
        data={"order_number": result.order_number},
        message="发货单生成成功"
    )

@router.get("/{shipment_id}")
async def get_shipment(shipment_id: int):
    """获取发货单详情"""
    shipment = find_shipment(shipment_id)
    
    if not shipment:
        raise NotFoundError("发货单不存在")
    
    return SuccessResponse.create(data=shipment)
```

### 3. 在 ApplicationService 中使用

```python
from app.application.base_app_service import BaseApplicationService
from app.exceptions import ValidationError, NotFoundError

class ShipmentApplicationService(BaseApplicationService):
    """发货应用服务"""
    
    def execute(self, command: dict) -> dict:
        """执行用例"""
        action = command.get("action")
        data = command.get("data", {})
        
        try:
            if action == "generate":
                return self._generate(data)
            else:
                raise BusinessError(f"未知操作：{action}")
        
        except ValidationError as e:
            self._logger.warning(f"验证失败：{e.message}")
            raise
        except NotFoundError as e:
            self._logger.warning(f"资源未找到：{e.message}")
            raise
        except Exception as e:
            self._logger.error(f"执行失败：{e}", exc_info=True)
            raise
    
    def _generate(self, data: dict) -> dict:
        """生成发货单"""
        # 验证必填字段
        if not data.get("items"):
            raise ValidationError("商品列表不能为空")
        
        # 业务逻辑
        # ...
        
        return self.success_response({
            "order_number": "SO12345"
        })
```

---

## 🔧 错误码规范

### 错误码格式

```
<分类>_<具体错误>
```

### 错误码列表

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 验证错误 |
| NOT_FOUND | 404 | 资源未找到 |
| AUTHENTICATION_ERROR | 401 | 认证失败 |
| AUTHORIZATION_ERROR | 403 | 授权失败 |
| BUSINESS_ERROR | 400 | 业务错误 |
| DATABASE_ERROR | 500 | 数据库错误 |
| EXTERNAL_SERVICE_ERROR | 503 | 外部服务错误 |
| RATE_LIMIT_ERROR | 429 | 请求频率限制 |
| NEURO_ERROR | 500 | Neuro 总线错误 |
| NEURO_TIMEOUT | 504 | Neuro 总线超时 |
| NEURO_NOT_FOUND | 404 | Neuro 处理器未找到 |
| INTERNAL_ERROR | 500 | 内部错误（未捕获异常） |

---

## 📝 最佳实践

### 1. 使用合适的异常类型

```python
# ✅ 好的做法
if not user:
    raise AuthenticationError("用户未登录")

if not has_permission:
    raise AuthorizationError("无权限访问")

if not resource:
    raise NotFoundError("资源不存在")

# ❌ 不好的做法
if not user or not has_permission:
    raise Exception("错误")  # 太笼统
```

### 2. 提供有意义的错误信息

```python
# ✅ 好的做法
raise ValidationError(f"订单号 {order_number} 不存在")

# ❌ 不好的做法
raise ValidationError("错误")  # 信息不明确
```

### 3. 使用自定义错误码

```python
# ✅ 好的做法
raise BusinessError(
    "库存不足",
    code="INSUFFICIENT_INVENTORY",
    data={"available": 10, "required": 100}
)

# ❌ 不好的做法
raise BusinessError("库存不足")  # 缺少错误码和上下文
```

### 4. 在边界处捕获异常

```python
# ✅ 好的做法 - 在 API 层捕获并转换
try:
    result = external_service.call()
except ExternalServiceError as e:
    logger.error(f"外部服务失败：{e}")
    raise BusinessError("服务暂时不可用", code="SERVICE_UNAVAILABLE")

# ❌ 不好的做法 - 直接抛出底层异常
result = external_service.call()  # 可能抛出各种底层异常
```

### 5. 记录适当的日志

```python
# ✅ 好的做法 - 记录关键信息
try:
    process_order(order_id)
except Exception as e:
    logger.error(f"订单处理失败：order_id={order_id}, error={e}", exc_info=True)
    raise

# ❌ 不好的做法 - 日志信息不完整
except Exception as e:
    logger.error("处理失败")  # 缺少上下文
    raise
```

---

## 🧪 测试示例

```python
import pytest
from fastapi.testclient import TestClient
from app.exceptions import ValidationError, NotFoundError

def test_validation_error(client: TestClient):
    """测试验证错误"""
    response = client.post("/api/shipment/generate", json={})
    
    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["code"] == "VALIDATION_ERROR"

def test_not_found_error(client: TestClient, auth_token: str):
    """测试资源未找到错误"""
    response = client.get(
        "/api/shipment/999999",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["code"] == "NOT_FOUND"

def test_success_response(client: TestClient, auth_token: str):
    """测试成功响应"""
    response = client.post(
        "/api/shipment/generate",
        json={"items": [...]},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "data" in data
```

---

## 🔄 迁移指南

### 从旧代码迁移到新错误处理

#### 1. 替换直接返回错误字典

```python
# ❌ 旧代码
if not shipment:
    return {"success": False, "error": "发货单不存在"}

# ✅ 新代码
if not shipment:
    raise NotFoundError("发货单不存在")
```

#### 2. 替换 HTTPException

```python
# ❌ 旧代码
from fastapi import HTTPException

if not user:
    raise HTTPException(status_code=401, detail="未认证")

# ✅ 新代码
from app.exceptions import AuthenticationError

if not user:
    raise AuthenticationError("用户未登录")
```

#### 3. 替换通用异常

```python
# ❌ 旧代码
try:
    process_data()
except Exception as e:
    return {"success": False, "error": str(e)}

# ✅ 新代码
try:
    process_data()
except Exception as e:
    logger.error(f"处理失败：{e}", exc_info=True)
    raise  # 让异常处理器统一处理
```

---

## 📊 监控和告警

### 1. 异常日志格式

```
[ERROR_CODE] Error message
Extra:
  - path: /api/endpoint
  - method: POST
  - user_id: 12345
```

### 2. 关键指标

- 异常数量（按错误码分类）
- 4xx 错误率
- 5xx 错误率
- 平均响应时间

### 3. 告警规则

- 5xx 错误率 > 1% → 告警
- 单个错误码激增 → 告警
- 数据库错误 → 立即告警

---

## 🎯 总结

统一错误处理机制提供了：

1. ✅ **标准化** - 统一的异常类和响应格式
2. ✅ **类型化** - 针对不同场景的异常类型
3. ✅ **可维护** - 集中管理，易于扩展
4. ✅ **可观测** - 详细的日志和错误信息
5. ✅ **易用性** - 简单的 API，清晰的文档

通过使用统一的错误处理机制，可以：

- 提高代码质量
- 改善用户体验
- 简化问题排查
- 便于监控告警

---

**文档版本**: v1.0  
**创建日期**: 2026-04-12  
**最后更新**: 2026-04-12
