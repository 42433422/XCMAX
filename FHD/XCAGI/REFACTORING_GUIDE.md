# XCAGI 架构重构实施指南

## 📖 文档说明

本文档是 XCAGI **v6.x～v9.x** 架构重构的**实施指南**（主栈已稳定在 FastAPI + Neuro-DDD），提供操作步骤、代码示例和最佳实践；**当前发布版本为 v9.0**。

**适用对象**:
- 开发团队：了解重构方向和具体实施步骤
- 测试团队：了解测试策略和验收标准
- 运维团队：了解架构变更对部署的影响

**文档版本**: v1.0  
**更新日期**: 2026-04-12

---

## 🎯 重构总览

### 为什么重构？

1. **代码可维护性**: 大型模块难以理解和维护
2. **测试覆盖不足**: 核心业务逻辑缺乏充分测试
3. **技术债务**: Flask + FastAPI 双框架增加复杂度
4. **文档缺失**: 开发者上手成本高

### 重构目标

| 维度 | 当前状态 | 目标状态 |
|------|---------|---------|
| 路由模块 | 单文件 >500 行 | 模块化，单文件 <200 行 |
| 测试覆盖率 | ~30% | HEAD **52.74%** / WIP **74.56%**（`metrics/coverage-dual-summary.json`） | >= 80% |
| 框架 | Flask + FastAPI | 纯 FastAPI |
| 文档 | 部分缺失 | 完整体系 |

---

## ✅ 第一阶段：已完成任务

### 1.1 模板路由模块化 (✅ 已完成)

#### 重构前

```
app/routes/
└── templates.py (500+ 行)
```

**问题**:
- 所有功能集中在一个文件
- 难以定位和维护
- 测试困难

#### 重构后

```
app/fastapi_routes/templates/
├── __init__.py          # 路由聚合
├── analyze.py           # 模板分析 (~120 行)
├── preview.py           # 模板预览 (~100 行)
└── validators.py        # 模板校验 (~180 行)
```

**优势**:
- ✅ 职责清晰，每个模块专注一个功能域
- ✅ 文件大小适中，易于阅读
- ✅ 独立测试，互不干扰

#### 实施步骤

1. **创建目录结构**
```bash
mkdir -p app/fastapi_routes/templates
```

2. **拆分逻辑**
   - `analyze.py`: Excel 文件分析（上传、解析）
   - `preview.py`: 模板预览（文件、网格、样式）
   - `validators.py`: 业务规则校验

3. **创建测试**
```bash
mkdir -p tests/unit/fastapi_routes/templates
```

4. **验证**
```bash
pytest tests/unit/fastapi_routes/templates/test_analyze.py -v
```

#### 代码示例

**analyze.py - 核心端点**:
```python
@router.post("/excel", summary="分析 Excel 文件")
async def analyze_excel(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Query(None),
    request: Request = None
):
    """分析上传的 Excel 文件，自动识别表头行并提取样例数据。"""
    try:
        import tempfile
        from app.routes.template_grid_core import _extract_structured_excel_preview
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        result = _extract_structured_excel_preview(tmp_path, sheet_name)
        
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"Excel 分析失败：{e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

**测试示例**:
```python
def test_analyze_excel_success(self, client, tmp_path):
    """测试 Excel 分析 - 成功场景"""
    from openpyxl import Workbook
    import tempfile
    
    # 创建测试 Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "测试表"
    ws.cell(row=1, column=1, value="产品型号")
    ws.cell(row=2, column=1, value="26-0200006A")
    
    # 保存并上传
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        wb.save(tmp.name)
        tmp_path = tmp.name
    
    with open(tmp_path, "rb") as f:
        response = client.post(
            "/api/templates/analyze/excel",
            files={"file": ("test.xlsx", f)}
        )
    
    assert response.status_code == 200
    assert response.json()["success"] is True
```

---

## 📋 第二阶段：进行中任务

### 1.2 发货路由模块化 (🔄 进行中)

#### 当前状态

```
app/fastapi_routes/shipment.py (150 行)
```

#### 目标结构

```
app/fastapi_routes/shipment/
├── __init__.py           # 路由聚合
├── generate.py           # 发货单生成
├── print.py              # 发货单打印
├── records.py            # 发货记录管理
├── sequence.py           # 订单号序列管理
└── schemas.py            # Pydantic 模型
```

#### 实施步骤

**步骤 1: 创建目录**
```bash
mkdir -p app/fastapi_routes/shipment
```

**步骤 2: 抽取 Pydantic 模型**
```python
# schemas.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class ShipmentGenerateRequest(BaseModel):
    """发货单生成请求"""
    customer_name: Optional[str] = Field(None, description="客户名称")
    items: Optional[List[Dict[str, Any]]] = Field(None, description="商品列表")
    order_text: Optional[str] = Field(None, description="订单文本")
    template_id: Optional[int] = Field(None, description="模板 ID")
    notes: Optional[str] = Field(None, description="备注")


class ShipmentPrintRequest(BaseModel):
    """发货单打印请求"""
    shipment_id: Optional[int] = Field(None, description="发货单 ID")
    filename: Optional[str] = Field(None, description="文件名")
    printer_name: Optional[str] = Field(None, description="打印机名称")
    label_data: Optional[Dict[str, Any]] = Field(None, description="标签数据")
```

**步骤 3: 拆分端点**
```python
# generate.py
from fastapi import APIRouter, Request
from app.fastapi_neuro_helper import _order_neuro
from .schemas import ShipmentGenerateRequest

router = APIRouter()


@router.post("/generate", summary="生成发货单")
async def shipment_generate(req: ShipmentGenerateRequest, request: Request):
    """生成发货单"""
    try:
        result = await _order_neuro(
            "ORDER_SHIPMENT_GENERATE",
            req.dict(exclude_none=True),
            request=request,
            timeout_ms=30000,
        )
        return result
    except Exception as e:
        logger.error(f"[Shipment Generate] 错误：{e}", exc_info=True)
        return {"success": False, "error": str(e)}
```

**步骤 4: 聚合路由**
```python
# __init__.py
from fastapi import APIRouter
from . import generate, print, records, sequence

router = APIRouter(prefix="/shipment", tags=["发货管理"])

router.include_router(generate.router, prefix="")
router.include_router(print.router, prefix="")
router.include_router(records.router, prefix="/shipment-records")
router.include_router(sequence.router, prefix="/sequence")

__all__ = ["router"]
```

**步骤 5: 更新主应用**
```python
# app/fastapi_routes/__init__.py
from .shipment import router as shipment_router

app.include_router(shipment_router, prefix="/api")
```

---

## 🔧 第三阶段：待实施任务

### 1.3 统一 ApplicationService 入口

#### 现状问题

```python
# ❌ 问题：路由层直接调用 services
from app.services.auth_service import get_auth_service
from app.services.user_service import get_user_service

# 路由层知道太多实现细节
result = auth_service.login(username, password)
```

#### 目标模式

```python
# ✅ 推荐：路由层只调用 application 层
from app.application.auth_app_service import get_auth_app_service

# 路由层只关心 HTTP 请求
result = auth_app_service.login(username, password)
```

#### 实施清单

| ApplicationService | 状态 | 文件路径 |
|-------------------|------|---------|
| `AuthAppService` | ✅ | `application/auth_app_service.py` |
| `ShipmentAppService` | ✅ | `application/shipment_app_service.py` |
| `ProductAppService` | ✅ | `application/product_app_service.py` |
| `MaterialAppService` | ⏳ | 待创建 |
| `PrintAppService` | ⏳ | 待创建 |
| `OCRAppService` | ⏳ | 待创建 |

#### 创建新的 ApplicationService

```python
# app/application/material_app_service.py
"""
物料管理应用服务

编排物料相关的业务用例。
"""

import logging
from typing import List, Optional

from app.application.ports.material_repository import MaterialRepository
from app.domain.product.entities import Material

logger = logging.getLogger(__name__)


class MaterialAppService:
    """物料应用服务"""
    
    def __init__(self, material_repository: MaterialRepository):
        self.material_repository = material_repository
    
    def get_all_materials(self, page: int = 1, per_page: int = 20) -> List[Material]:
        """获取所有物料（分页）"""
        return self.material_repository.find_all(page, per_page)
    
    def get_material_by_id(self, material_id: int) -> Optional[Material]:
        """根据 ID 获取物料"""
        return self.material_repository.find_by_id(material_id)
    
    def create_material(self, material_data: dict) -> Material:
        """创建物料"""
        material = Material(**material_data)
        return self.material_repository.save(material)


# 工厂函数
_material_app_service_instance = None


def get_material_app_service() -> MaterialAppService:
    """获取物料应用服务实例"""
    global _material_app_service_instance
    if _material_app_service_instance is None:
        from app.infrastructure.repositories.material_repository_impl import MaterialRepositoryImpl
        repo = MaterialRepositoryImpl()
        _material_app_service_instance = MaterialAppService(repo)
    return _material_app_service_instance
```

---

### 1.4 完善端口层接口定义

#### 目标

为所有 Port 接口添加：
- ✅ 详细文档字符串
- ✅ 类型注解
- ✅ 使用示例

#### 示例模板

```python
# app/application/ports/product_repository.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Protocol

from app.domain.product.entities import Product


class ProductRepository(Protocol):
    """产品仓储接口（Port）。
    
    定义产品持久化的抽象接口，具体实现由 Infrastructure 层提供。
    
    **职责**:
    - 保存产品实体
    - 查询产品（按 ID、SKU、名称等）
    - 删除产品
    
    **使用示例**:
    ```python
    # Infrastructure 层实现
    class PostgreSQLProductRepository:
        def __init__(self, session: Session):
            self.session = session
        
        def save(self, product: Product) -> Product:
            self.session.add(product)
            self.session.commit()
            return product
        
        def find_by_id(self, product_id: int) -> Optional[Product]:
            return self.session.query(Product).filter_by(id=product_id).first()
    ```
    """
    
    @abstractmethod
    def save(self, product: Product) -> Product:
        """保存产品。
        
        Args:
            product: 产品实体
            
        Returns:
            保存后的产品实体
            
        Raises:
            IntegrityError: 如果产品已存在
        """
        raise NotImplementedError
    
    @abstractmethod
    def find_by_id(self, product_id: int) -> Optional[Product]:
        """根据 ID 查找产品。
        
        Args:
            product_id: 产品 ID
            
        Returns:
            产品实体，不存在返回 None
        """
        raise NotImplementedError
    
    @abstractmethod
    def find_by_sku(self, sku: str) -> Optional[Product]:
        """根据 SKU 查找产品。
        
        Args:
            sku: 产品 SKU
            
        Returns:
            产品实体，不存在返回 None
        """
        raise NotImplementedError
    
    @abstractmethod
    def find_all(self, page: int = 1, per_page: int = 20) -> List[Product]:
        """分页获取所有产品。
        
        Args:
            page: 页码（从 1 开始）
            per_page: 每页数量
            
        Returns:
            产品列表
        """
        raise NotImplementedError
    
    @abstractmethod
    def delete(self, product_id: int) -> bool:
        """删除产品。
        
        Args:
            product_id: 产品 ID
            
        Returns:
            是否删除成功
        """
        raise NotImplementedError
```

---

### 2.1 核心领域服务单元测试

#### 测试策略

**测试金字塔**:
```
        /\
       /  \      E2E 测试 (10%)
      /----\    
     /      \   集成测试 (20%)
    /--------\  
   /          \ 单元测试 (70%)
  /------------\
```

#### 测试目录结构

```
tests/
├── unit/                      # 单元测试
│   ├── domain/                # 领域层测试
│   │   ├── test_intent_domain.py
│   │   ├── test_shipment_domain.py
│   │   └── test_product_domain.py
│   ├── application/           # 应用层测试
│   │   ├── test_auth_app_service.py
│   │   └── test_shipment_app_service.py
│   └── infrastructure/        # 基础设施层测试
│       └── test_repositories.py
├── integration/               # 集成测试
│   ├── test_api_auth.py
│   ├── test_api_shipment.py
│   └── test_api_products.py
└── e2e/                       # E2E 测试
    ├── test_shipment_flow.py
    └── test_order_flow.py
```

#### 编写高质量单元测试

**示例：意图识别领域测试**

```python
# tests/unit/domain/test_intent_domain.py
import pytest
from unittest.mock import Mock, patch
from app.domain.services.intent_recognition_service import IntentRecognitionService
from app.domain.value_objects import Intent, IntentType


class TestIntentRecognitionService:
    """意图识别服务单元测试"""
    
    @pytest.fixture
    def service(self):
        """创建服务实例（使用 Mock 依赖）"""
        mock_bert_service = Mock()
        mock_deepseek_service = Mock()
        return IntentRecognitionService(
            bert_service=mock_bert_service,
            deepseek_service=mock_deepseek_service
        )
    
    def test_recognize_greeting_intent(self, service):
        """测试识别问候意图"""
        user_input = "你好"
        
        # 配置 Mock 返回值
        service.bert_service.recognize.return_value = Intent(
            type=IntentType.GREETING,
            confidence=0.95
        )
        
        result = service.recognize(user_input)
        
        assert result.type == IntentType.GREETING
        assert result.confidence > 0.9
        self.bert_service.recognize.assert_called_once_with(user_input)
    
    def test_recognize_with_fallback(self, service):
        """测试降级识别（BERT 失败时使用 DeepSeek）"""
        user_input = "我想查询订单"
        
        # BERT 失败
        service.bert_service.recognize.side_effect = Exception("BERT 服务不可用")
        
        # DeepSeek 成功
        service.deepseek_service.recognize.return_value = Intent(
            type=IntentType.ORDER_QUERY,
            confidence=0.88
        )
        
        result = service.recognize(user_input)
        
        assert result.type == IntentType.ORDER_QUERY
        assert service.deepseek_service.recognize.called
    
    def test_recognize_low_confidence_requires_confirmation(self, service):
        """测试低置信度需要确认"""
        user_input = "可能是想查询订单"
        
        service.bert_service.recognize.return_value = Intent(
            type=IntentType.ORDER_QUERY,
            confidence=0.45  # 低置信度
        )
        
        result = service.recognize(user_input)
        
        assert result.confidence < 0.5
        assert result.requires_confirmation is True
```

#### 覆盖率目标

| 模块 | 当前覆盖率 | 目标覆盖率 | 优先级 |
|------|-----------|-----------|--------|
| `domain/intent` | ~30% | 90% | P0 |
| `domain/shipment` | ~40% | 85% | P0 |
| `domain/product` | ~20% | 85% | P0 |
| `application/services` | ~35% | 80% | P1 |
| `infrastructure` | ~25% | 75% | P2 |

#### 运行测试并生成报告

```bash
# 运行所有测试
pytest tests/unit -v

# 生成覆盖率报告
pytest tests/unit --cov=app --cov-report=html

# 查看 HTML 报告
open htmlcov/index.html
```

---

### 2.2 API 集成测试

#### 测试策略

**集成测试 vs 单元测试**:
- 单元测试：测试单个类/函数（Mock 外部依赖）
- 集成测试：测试多个组件协作（使用真实数据库）

#### 配置测试数据库

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.fastapi_app import create_app

@pytest.fixture(scope="session")
def test_engine():
    """创建测试数据库引擎（SQLite 内存）"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return engine

@pytest.fixture
def test_session(test_engine):
    """创建测试会话"""
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def client(test_session):
    """创建测试客户端"""
    app = create_app()
    # 注入测试会话
    app.state.db_session = test_session
    return TestClient(app)
```

#### 编写集成测试

```python
# tests/integration/test_api_shipment.py
import pytest
from fastapi.testclient import TestClient
from app.fastapi_app import create_app
from app.db.models.shipment import ShipmentRecord


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_token(client):
    """获取认证 token"""
    response = client.post("/api/auth/login", json={
        "username": "test_user",
        "password": "test_password"
    })
    return response.json()["access_token"]


class TestShipmentAPIIntegration:
    """发货管理 API 集成测试"""
    
    def test_create_shipment_success(self, client, auth_token, test_session):
        """测试创建发货单 - 完整流程"""
        # 准备测试数据
        payload = {
            "customer_name": "测试客户",
            "items": [
                {"product_id": 1, "quantity": 100, "unit_price": 25.5}
            ]
        }
        
        # 执行请求
        response = client.post(
            "/api/shipment/generate",
            json=payload,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # 验证响应
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "shipment_id" in data
        
        # 验证数据库
        shipment_id = data["shipment_id"]
        shipment = test_session.query(ShipmentRecord).filter_by(id=shipment_id).first()
        assert shipment is not None
        assert shipment.customer_name == "测试客户"
    
    def test_get_shipment_records_pagination(self, client, auth_token, test_session):
        """测试分页获取发货记录"""
        # 准备测试数据
        for i in range(25):
            shipment = ShipmentRecord(
                customer_name=f"客户{i}",
                total_amount=100.0 * i
            )
            test_session.add(shipment)
        test_session.commit()
        
        # 请求第一页
        response = client.get(
            "/api/shipment/shipment-records/records?page=1&per_page=20",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) == 20
        assert data["total"] == 25
        
        # 请求第二页
        response = client.get(
            "/api/shipment/shipment-records/records?page=2&per_page=20",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) == 5
```

---

### 2.3 E2E 测试场景

#### 配置 Playwright

```python
# tests/e2e/conftest.py
import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def browser():
    """创建浏览器实例"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """创建页面实例"""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def base_url():
    """测试环境 URL"""
    return "http://localhost:5173"
```

#### 编写 E2E 测试

```python
# tests/e2e/test_shipment_flow.py
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_complete_shipment_flow(page: Page, base_url: str):
    """测试完整发货流程"""
    
    # 1. 登录
    page.goto(f"{base_url}/login")
    page.fill('input[name="username"]', "test_user")
    page.fill('input[name="password"]', "test_password")
    page.click('button[type="submit"]')
    
    # 验证登录成功
    expect(page).to_have_url(f"{base_url}/dashboard")
    expect(page.locator('.user-welcome')).to_contain_text("test_user")
    
    # 2. 创建发货单
    page.click('text=发货管理')
    page.click('text=创建发货单')
    
    # 填写表单
    page.fill('input[name="customer_name"]', "测试客户")
    page.fill('input[name="product_name"]', "PU 亮光白色漆")
    page.fill('input[name="quantity"]', "100")
    page.fill('input[name="unit_price"]', "25.5")
    
    # 提交
    page.click('button[type="submit"]')
    
    # 验证创建成功
    expect(page.locator('.alert-success')).to_be_visible()
    expect(page.locator('.shipment-id')).to_contain_text("#")
    
    # 3. 打印发货单
    page.click('text=打印')
    page.select_option('select[name="printer"]', "测试打印机")
    page.click('button:has-text("确认打印")')
    
    # 验证打印任务创建
    expect(page.locator('.print-job-created')).to_be_visible()
    expect(page.locator('.print-job-status')).to_contain_text("已发送")
```

#### 运行 E2E 测试

```bash
# 运行所有 E2E 测试
pytest tests/e2e -v

# 运行特定标记的测试
pytest tests/e2e -m e2e -v

# 生成 HTML 报告
pytest tests/e2e --html=report.html
```

---

## 📚 文档完善

### 3.1 API 文档自动生成

#### 配置 FastAPI OpenAPI

```python
# app/fastapi_app.py
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(
    title="XCAGI API",
    description="""
XCAGI v8.0 - AI 单据智能处理系统 API

## 核心功能

- **AI 智能聊天**: 混合意图识别 + 上下文对话
- **OCR 单据识别**: Excel/PDF 自动解析
- **标签打印**: 自动模板生成 + 条码打印
- **出货管理**: 发货单生成 + 合同打印
- **库存管理**: 实时库存查询 + 预警

## 技术栈

- **后端**: FastAPI + SQLAlchemy
- **前端**: Vue 3 + TypeScript
- **数据库**: PostgreSQL + pgvector
- **缓存**: Redis
- **AI**: BERT + DeepSeek + PaddleOCR
    """,
    version="5.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)
```

#### 为端点添加详细文档

```python
@router.post("/generate", summary="生成发货单")
async def shipment_generate(req: ShipmentGenerateRequest, request: Request):
    """
    生成发货单
    
    根据客户信息和商品列表自动生成发货单，支持自定义模板。
    
    **请求参数**:
    - `customer_name`: 客户名称（可选）
    - `items`: 商品列表，每项包含 `product_id`, `quantity`, `unit_price`
    - `order_text`: 订单文本描述（可选）
    - `template_id`: 模板 ID（可选，默认使用系统模板）
    - `notes`: 备注信息（可选）
    
    **返回示例**:
    ```json
    {
      "success": true,
      "data": {
        "shipment_id": 12345,
        "order_number": "SO20260412001",
        "created_at": "2026-04-12T10:30:00"
      }
    }
    ```
    
    **错误码**:
    - `400`: 请求参数错误
    - `401`: 未认证
    - `500`: 服务器内部错误
    
    **安全**:
    - 需要 Bearer Token 认证
    """
```

---

### 3.2 开发者快速入门

#### 文档大纲

```markdown
# XCAGI 开发者快速入门

## 1. 环境准备

### 必需软件
- Python 3.11+
- Node.js 18+
- PostgreSQL 16
- Redis 7

### 可选工具
- Docker Desktop
- VS Code / PyCharm
- Postman

## 2. 快速开始

### 2.1 克隆项目
```bash
git clone https://github.com/42433422/xcagi.git
cd xcagi
```

### 2.2 安装依赖
```bash
# 后端
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 2.3 配置数据库
```bash
# 创建数据库
createdb xcagi

# 初始化表结构
psql -d xcagi -f alembic.ini
alembic upgrade head
```

### 2.4 配置环境变量
```bash
# 复制示例配置
cp .env.example .env

# 编辑配置
vim .env
```

### 2.5 启动服务
```bash
# 后端（开发模式）
python -m uvicorn app.fastapi_app:app --reload --port 5000

# 前端
cd frontend
npm run dev
```

## 3. 项目结构

```
xcagi/
├── app/                      # 后端应用
│   ├── domain/               # 领域层
│   ├── application/          # 应用层
│   ├── infrastructure/       # 基础设施层
│   ├── fastapi_routes/       # API 路由
│   └── services/             # 业务服务
├── frontend/                 # 前端应用
│   ├── src/
│   │   ├── api/              # API 客户端
│   │   ├── components/       # 组件
│   │   ├── stores/           # 状态管理
│   │   └── views/            # 页面
│   └── public/
└── tests/                    # 测试
```

## 4. 开发规范

### 4.1 代码风格
- Python: Black + Flake8
- JavaScript/TypeScript: ESLint + Prettier

### 4.2 Git 工作流
```bash
# 创建功能分支
git checkout -b feature/your-feature

# 提交代码
git add .
git commit -m "feat: add new feature"

# 推送并创建 PR
git push origin feature/your-feature
```

### 4.3 测试要求
- 新功能必须包含单元测试
- 核心业务逻辑覆盖率 >= 80%
- 运行测试：`pytest tests/unit -v`

## 5. 常见问题

### Q: 数据库连接失败？
A: 检查 PostgreSQL 服务是否启动，DATABASE_URL 配置是否正确。

### Q: 前端跨域问题？
A: 确认后端 CORS 配置包含前端地址。
```

---

## 🎯 成功指标

### 代码质量指标

- [x] 路由模块单文件 < 200 行
- [ ] 单元测试覆盖率 >= 80%
- [ ] 集成测试覆盖所有核心 API
- [ ] E2E 测试覆盖关键业务流程
- [ ] 代码重复率 < 5%

### 性能指标

- [ ] API P95 响应时间 < 200ms
- [ ] 数据库查询 P95 < 100ms
- [ ] 页面加载时间 < 2s
- [ ] 系统可用性 >= 99.9%

### 开发效率指标

- [ ] 新开发者上手时间 < 1 天
- [ ] 代码审查时间减少 30%
- [ ] Bug 修复时间减少 40%
- [ ] 部署时间 < 5 分钟

---

## 📅 下一步行动

### 本周任务

1. [ ] 完成 shipment 路由模块化
2. [ ] 创建 3 个新的 ApplicationService
3. [ ] 编写 10 个核心领域单元测试
4. [ ] 完善 Ports 层接口文档

### 本月任务

1. [ ] 完成所有路由模块化
2. [ ] 测试覆盖率达到 60%
3. [ ] 发布 API 文档
4. [ ] 编写开发者指南

### 本季度任务

1. [ ] 测试覆盖率达到 80%
2. [ ] 完成 FastAPI 迁移
3. [ ] 性能优化达标
4. [ ] 完整文档体系

---

## 🔧 附录：工具与资源

### 开发工具

- **IDE**: VS Code / PyCharm
- **API 测试**: Postman / Insomnia
- **数据库**: DBeaver / pgAdmin
- **终端**: Windows Terminal / iTerm2

### 测试工具

- **单元测试**: pytest
- **E2E 测试**: Playwright
- **覆盖率**: pytest-cov
- **性能测试**: locust

### 文档工具

- **API 文档**: Swagger / ReDoc
- **项目文档**: MkDocs
- **图表**: Mermaid / Draw.io

---

**文档状态**: 草稿  
**最后更新**: 2026-04-12  
**负责人**: 首席架构师  
**联系方式**: architecture@xcagi.com
