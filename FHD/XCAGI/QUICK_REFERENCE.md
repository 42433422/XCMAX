# XCAGI 架构重构 - 快速参考指南

**版本**: v1.0  
**更新日期**: 2026-04-12  
**适用对象**: 开发团队、测试团队、运维团队

---

## 🚀 快速开始

### 1. 运行测试

```bash
# 运行所有重构测试
python run_refactoring_tests.py -v

# 生成覆盖率报告
python run_refactoring_tests.py -v -c

# 生成 HTML 报告
python run_refactoring_tests.py -v -c --html
```

### 2. 启动 FastAPI 应用

```bash
# 开发模式
python -m uvicorn app.fastapi_app:app --reload --host 0.0.0.0 --port 8000

# 生产模式
python -m uvicorn app.fastapi_app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3. 访问 API 文档

```
Swagger UI: http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
```

---

## 📁 模块化路由结构

### templates 模块

```
app/fastapi_routes/templates/
├── __init__.py          # 统一导出
├── analyze.py           # 模板分析
├── preview.py           # 模板预览
└── validators.py        # 模板校验
```

**API 端点**:
- `POST /api/templates/analyze/excel` - 分析 Excel 文件
- `GET /api/templates/analyze/file` - 分析指定文件
- `POST /api/templates/preview/file` - 预览 Excel 文件
- `POST /api/templates/validators/validate` - 校验模板
- `GET /api/templates/validators/rules` - 获取校验规则

---

### shipment 模块

```
app/fastapi_routes/shipment/
├── __init__.py          # 统一导出
├── schemas.py           # Pydantic 模型
├── generate.py          # 发货单生成
├── print.py             # 发货单打印
├── records.py           # 发货记录管理
└── sequence.py          # 订单号序列
```

**API 端点**:
- `POST /api/shipment/shipment/generate` - 生成发货单
- `POST /api/shipment/shipment/generate-batch` - 批量生成
- `POST /api/shipment/shipment/print` - 打印发货单
- `GET /api/shipment/shipment/records/records` - 获取记录列表
- `PATCH /api/shipment/shipment/records/record` - 更新记录
- `POST /api/shipment/shipment/sequence/set` - 设置序列

---

## 🧪 测试编写指南

### 1. 测试文件命名

```
tests/unit/fastapi_routes/<module>/test_<module>.py
```

### 2. 测试类结构

```python
import pytest
from fastapi.testclient import TestClient
from app.fastapi_app import create_fastapi_app

@pytest.fixture
def client():
    """创建测试客户端"""
    app = create_fastapi_app(enable_docs=False, enable_cors=False)
    return TestClient(app)

class TestModule:
    """模块测试类"""
    
    def test_feature_success(self, client):
        """测试功能 - 成功场景"""
        payload = {"key": "value"}
        response = client.post("/api/endpoint", json=payload)
        assert response.status_code == 200
    
    def test_feature_failure(self, client):
        """测试功能 - 失败场景"""
        payload = {"invalid": "data"}
        response = client.post("/api/endpoint", json=payload)
        assert response.status_code == 422
```

### 3. Pydantic 模型测试

```python
from app.fastapi_routes.shipment.schemas import ShipmentItem

def test_model_validation():
    """测试模型验证"""
    # 有效数据
    item = ShipmentItem(product_id=1, quantity=100)
    assert item.quantity == 100
    
    # 无效数据应该抛出异常
    with pytest.raises(Exception):
        ShipmentItem(product_id=1, quantity=-100)
```

---

## 🔧 Neuro-DDD 集成

### 1. 端点调用 Neuro 总线

```python
from app.fastapi_neuro_helper import _order_neuro

@router.post("/generate")
async def shipment_generate(req: ShipmentGenerateRequest, request: Request):
    try:
        payload = req.dict(exclude_none=True)
        
        result = await _order_neuro(
            "ORDER_SHIPMENT_GENERATE",
            payload,
            request=request,
            timeout_ms=30000,
        )
        
        return ShipmentGenerateResponse(
            success=result.get("success", True),
            shipment_id=result.get("shipment_id"),
            error=result.get("error")
        )
    except Exception as e:
        logger.error(f"错误：{e}", exc_info=True)
        return ShipmentGenerateResponse(success=False, error=str(e))
```

### 2. Neuro 信号类型

- `ORDER_SHIPMENT_GENERATE` - 生成发货单
- `ORDER_SHIPMENT_LIST` - 获取发货记录列表
- `ORDER_SHIPMENT_UPDATE` - 更新发货记录
- `ORDER_SHIPMENT_DELETE` - 删除发货记录
- `PRINT_JOB_CREATE` - 创建打印任务
- `PRINT_JOB_STATUS` - 查询打印状态

---

## 📊 Pydantic 模型使用

### 1. 定义模型

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class ShipmentItem(BaseModel):
    """发货单项"""
    
    product_id: int = Field(..., description="产品 ID")
    quantity: float = Field(..., ge=0, description="数量")
    unit_price: Optional[float] = Field(None, ge=0, description="单价")
    
    class Config:
        json_schema_extra = {
            "example": {
                "product_id": 1,
                "quantity": 100,
                "unit_price": 25.5
            }
        }
```

### 2. 使用模型

```python
@router.post("/generate", response_model=ShipmentGenerateResponse)
async def shipment_generate(req: ShipmentGenerateRequest):
    # 自动验证请求数据
    # req.customer_name, req.items 等字段已验证
    
    # 处理业务逻辑
    ...
    
    # 返回响应（自动验证）
    return ShipmentGenerateResponse(
        success=True,
        shipment_id=12345,
        order_number="SO20260412001"
    )
```

---

## 🐛 常见问题排查

### 1. 路由未注册（404 错误）

**问题**: 访问端点返回 404

**解决**:
```python
# 检查路由是否在 __init__.py 中注册
# app/fastapi_routes/__init__.py

def _register_shipment(app: FastAPI):
    from app.fastapi_routes.shipment import router as shipment_router
    app.include_router(shipment_router, prefix="/api/shipment")
```

### 2. 测试导入失败

**问题**: `ImportError: attempted relative import`

**解决**:
```python
# 使用绝对导入
from app.fastapi_routes.shipment.schemas import ShipmentItem

# 不要使用相对导入
# from .schemas import ShipmentItem  # ❌
```

### 3. Pydantic 验证失败

**问题**: 请求数据验证不通过

**解决**:
```python
# 检查字段类型和约束
class MyModel(BaseModel):
    quantity: float = Field(..., ge=0)  # ge=0 表示 >= 0
    
# 确保请求数据符合模型定义
```

### 4. Neuro-DDD 调用超时

**问题**: Neuro 信号处理超时

**解决**:
```python
# 增加超时时间
result = await _order_neuro(
    "SIGNAL_NAME",
    payload,
    request=request,
    timeout_ms=60000,  # 增加到 60 秒
)
```

---

## 📝 代码规范

### 1. 文件命名

- ✅ `analyze.py` - 小写，下划线分隔
- ❌ `Analyze.py`, `analyzeTool.py`

### 2. 类命名

- ✅ `ShipmentGenerateRequest` - 大驼峰
- ❌ `shipmentGenerateRequest`, `shipment_generate_request`

### 3. 函数命名

- ✅ `async def shipment_generate():` - 小写，下划线分隔
- ❌ `async def shipmentGenerate():`

### 4. 常量命名

- ✅ `_TERM_EQUIVALENTS = {...}` - 大写，下划线分隔
- ❌ `_termEquivalents = {...}`

---

## 🔍 调试技巧

### 1. 查看路由列表

```bash
# 启动应用后访问
http://localhost:8000/docs
```

### 2. 查看日志

```python
# 在代码中添加日志
import logging
logger = logging.getLogger(__name__)

logger.info("信息日志")
logger.warning("警告日志")
logger.error("错误日志", exc_info=True)
```

### 3. 调试 Neuro 信号

```python
# 在调用前后添加日志
logger.info(f"调用 Neuro 信号：ORDER_SHIPMENT_GENERATE")
logger.debug(f"载荷：{payload}")

result = await _order_neuro(...)

logger.info(f"Neuro 响应：{result}")
```

---

## 📚 文档资源

### 核心文档

- `REFACTORING_PLAN.md` - 重构实施计划
- `REFACTORING_GUIDE.md` - 重构指南
- `REFACTORING_SUMMARY.md` - 重构总结
- `FINAL_COMPLETION_REPORT.md` - 完成报告

### 外部资源

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Pydantic 官方文档](https://docs.pydantic.dev/)
- [pytest 官方文档](https://docs.pytest.org/)

---

## 🎯 最佳实践

### 1. 端点实现

```python
@router.post("/endpoint", summary="简短描述", response_model=ResponseModel)
async def endpoint_handler(req: RequestModel, request: Request):
    """
    详细的端点描述
    
    **功能**:
    - 功能点 1
    - 功能点 2
    
    **请求参数**:
    - `param1`: 参数描述
    
    **返回示例**:
    ```json
    {"success": true, "data": {...}}
    ```
    
    **错误码**:
    - `400`: 请求参数错误
    - `500`: 服务器内部错误
    """
    try:
        # 业务逻辑
        ...
    except Exception as e:
        logger.error(f"错误：{e}", exc_info=True)
        return ErrorResponseModel(success=False, error=str(e))
```

### 2. 错误处理

```python
try:
    # 业务逻辑
    result = await some_operation()
    
    if not result:
        return ErrorResponseModel(success=False, error="操作失败")
    
    return SuccessResponseModel(success=True, data=result)
    
except ValidationError as e:
    logger.warning(f"验证错误：{e}")
    return ErrorResponseModel(success=False, error="数据验证失败", code=400)
    
except Exception as e:
    logger.error(f"未预期错误：{e}", exc_info=True)
    return ErrorResponseModel(success=False, error="服务器内部错误", code=500)
```

### 3. 日志记录

```python
# 不同级别日志的使用场景
logger.debug("调试信息 - 详细数据")      # 开发调试
logger.info("信息 - 正常流程")          # 业务流程
logger.warning("警告 - 可恢复错误")     # 可恢复异常
logger.error("错误 - 不可恢复错误", exc_info=True)  # 严重错误
```

---

## 🚀 性能优化建议

### 1. 数据库查询

```python
# ❌ N+1 查询问题
for item in items:
    product = db.query(Product).filter(Product.id == item.product_id).first()

# ✅ 批量查询
product_ids = [item.product_id for item in items]
products = db.query(Product).filter(Product.id.in_(product_ids)).all()
```

### 2. 异步处理

```python
# 使用异步 IO
async def process_items(items):
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks)
    return results
```

### 3. 缓存使用

```python
# 使用 Redis 缓存
from app.core.cache import cache

@cache.cached(timeout=300)
async def get_expensive_data(key):
    # 耗时操作
    return await expensive_operation()
```

---

## 📞 支持与反馈

**技术支持**: 架构组  
**反馈渠道**: 
- 代码审查
- 团队周会
- 技术讨论群

**紧急联系**: 
- 技术负责人：[联系方式]
- 架构师：[联系方式]

---

**最后更新**: 2026-04-12  
**版本**: v1.0  
**状态**: 已发布
