# MOD 商店系统使用指南

## 📦 目录

1. [概述](#概述)
2. [快速开始](#快速开始)
3. [MOD 开发指南](#mod 开发指南)
4. [MOD 打包工具](#mod 打包工具)
5. [API 参考](#api 参考)
6. [前端使用](#前端使用)
7. [最佳实践](#最佳实践)

---

## 概述

MOD 商店系统是一个完整的扩展管理平台，允许开发者创建、分发和管理 XCAGI 系统的功能扩展。

### 核心功能

- ✅ **MOD 打包与签名** - 标准的 .xcmod 格式，支持数字签名
- ✅ **上传与下载** - RESTful API 支持文件传输
- ✅ **安装与卸载** - 一键安装/卸载 MOD
- ✅ **版本管理** - 自动检测更新，支持版本回滚
- ✅ **依赖解析** - 自动检查和安装依赖
- ✅ **元数据索引** - SQLite 数据库存储 MOD 信息
- ✅ **搜索与筛选** - 全文搜索、分类筛选
- ✅ **评分系统** - 用户评价和评分
- ✅ **统计追踪** - 下载量、安装量统计

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      前端 (Vue 3)                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ ModStore    │  │ ModDetails  │  │ API Client  │         │
│  │ Component   │  │ Component   │  │ (TypeScript)│         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                            ↓ HTTP/REST
┌─────────────────────────────────────────────────────────────┐
│                   后端 (FastAPI)                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MOD Store API Routes                    │   │
│  │  /api/mod-store/catalog    - 获取 MOD 目录            │   │
│  │  /api/mod-store/upload     - 上传 MOD                 │   │
│  │  /api/mod-store/install    - 安装 MOD                 │   │
│  │  /api/mod-store/uninstall  - 卸载 MOD                 │   │
│  │  /api/mod-store/update     - 更新 MOD                 │   │
│  │  /api/mod-store/search     - 搜索 MOD                 │   │
│  │  /api/mod-store/rate       - 评分 MOD                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  MOD 管理层                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ ModManager   │  │ ModPackage   │  │ ModIndex     │      │
│  │ (生命周期)   │  │ (打包/签名)  │  │ (索引服务)   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  持久化层                                    │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ mods/        │  │ mod_index.db │                         │
│  │ (MOD 文件)    │  │ (SQLite)     │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 环境准备

确保已安装以下依赖：

```bash
# Python 依赖
pip install cryptography

# 前端依赖
cd frontend
npm install
```

### 2. 配置环境变量

在 `.env` 文件中添加：

```bash
# MOD 商店配置
XCAGI_MOD_STORE_DIR=/path/to/mod_store
XCAGI_MODS_ROOT=/path/to/mods
XCAGI_MOD_SIGNER=your_name
XCAGI_MOD_PUBLIC_KEY=/path/to/public_key.pem  # 可选
```

### 3. 启动服务

```bash
# 启动后端
python run.py

# 启动前端
cd frontend
npm run dev
```

### 4. 访问 MOD 商店

浏览器访问：`http://localhost:5173/mod-store`

---

## MOD 开发指南

### MOD 目录结构

```
my-mod/
├── manifest.json              # 必需：MOD 元数据
├── backend/
│   ├── __init__.py
│   ├── blueprints.py          # Flask 路由蓝图
│   ├── services.py            # 业务逻辑
│   └── hooks.py               # 钩子处理
├── frontend/
│   ├── routes.js              # Vue 路由
│   ├── components/            # Vue 组件
│   └── views/                 # 页面视图
├── config/
│   └── industry_overrides.yaml
└── data/
    └── *.json
```

### manifest.json 详解

```json
{
  "id": "my-mod",
  "name": "我的 MOD",
  "version": "1.0.0",
  "author": "开发者名称",
  "description": "MOD 描述",
  "primary": false,
  "dependencies": {
    "xcagi": ">=5.0.0",
    "other-mod": ">=1.0.0"
  },
  "backend": {
    "entry": "blueprints",
    "init": "mod_init"
  },
  "frontend": {
    "routes": "routes",
    "menu": [
      {
        "id": "my-menu",
        "label": "我的菜单",
        "icon": "fa-star",
        "path": "/my-mod"
      }
    ]
  },
  "hooks": {
    "shipment.created": "services.on_shipment_created"
  },
  "comms": {
    "exports": ["inventory.query", "pricing.calculate"]
  },
  "workflow_employees": [
    {
      "id": "my_worker",
      "label": "我的工作流",
      "panel_summary": "工作流描述"
    }
  ]
}
```

### 后端开发示例

**blueprints.py**

```python
from flask import Blueprint, jsonify

def create_blueprint(mod_id: str):
    bp = Blueprint(mod_id, __name__, url_prefix=f"/{mod_id}")
    
    @bp.route("/hello", methods=["GET"])
    def hello():
        return jsonify({
            "success": True,
            "data": {"message": f"Hello from {mod_id}!"}
        })
    
    return bp

def register_blueprints(app, mod_id: str):
    bp = create_blueprint(mod_id)
    app.register_blueprint(bp)
```

**services.py**

```python
def mod_init():
    """MOD 初始化函数"""
    print(f"MOD {mod_id} initialized")

def on_shipment_created(shipment_data):
    """钩子处理函数"""
    print(f"Shipment created: {shipment_data['id']}")
```

### 前端开发示例

**routes.js**

```javascript
const myModRoutes = [
  {
    path: '/my-mod',
    name: 'my-mod-home',
    component: () => import('./views/Home.vue'),
    meta: { 
      title: '我的 MOD',
      mod: 'my-mod'
    }
  }
];

const myModMenu = [
  {
    id: 'my-mod-home',
    label: '首页',
    icon: 'fa-home',
    path: '/my-mod'
  }
];

export { myModRoutes, myModMenu };
```

---

## MOD 打包工具

### 安装

打包工具位于 `tools/mod_pack.py`

### 使用示例

#### 1. 打包 MOD

```bash
# 基本用法
python tools/mod_pack.py pack my-mod/

# 指定输出目录
python tools/mod_pack.py pack my-mod/ -o output/

# 不生成签名
python tools/mod_pack.py pack my-mod/ --no-sign

# 排除特定文件
python tools/mod_pack.py pack my-mod/ --exclude "__pycache__,*.pyc,.git"

# 打包并验证
python tools/mod_pack.py pack my-mod/ --verify
```

#### 2. 解包 MOD

```bash
# 解包到当前目录
python tools/mod_pack.py unpack my-mod-1.0.0.xcmod

# 解包到指定目录
python tools/mod_pack.py unpack my-mod-1.0.0.xcmod -o extracted/

# 不验证签名
python tools/mod_pack.py unpack my-mod-1.0.0.xcmod --no-verify
```

#### 3. 验证 MOD 包

```bash
python tools/mod_pack.py validate my-mod-1.0.0.xcmod
```

输出示例：
```
✅ MOD 包验证通过
   MOD ID: my-mod
   名称：我的 MOD
   版本：1.0.0
   作者：开发者名称
```

#### 4. 查看 MOD 信息

```bash
python tools/mod_pack.py info my-mod-1.0.0.xcmod
```

输出示例：
```
=== MOD 包信息 ===
ID:      my-mod
名称：    我的 MOD
版本：    1.0.0
作者：    开发者名称
描述：    MOD 描述

=== 后端扩展 ===
入口：    blueprints
初始化：  mod_init

=== 前端扩展 ===
路由：    routes
菜单项：  1 个
         - 我的菜单 (/my-mod)

=== 钩子 ===
   shipment.created -> services.on_shipment_created

=== 通信通道 ===
   - inventory.query
   - pricing.calculate

=== 工作流员工 ===
   - 我的工作流 (my_worker)
```

#### 5. 为 MOD 包签名

```bash
# 生成 RSA 密钥对
openssl genrsa -out private_key.pem 2048
openssl rsa -in private_key.pem -pubout -out public_key.pem

# 签名 MOD 包
python tools/mod_pack.py sign my-mod-1.0.0.xcmod --key private_key.pem

# 签名并输出到新文件
python tools/mod_pack.py sign my-mod-1.0.0.xcmod --key private_key.pem -o my-mod-signed.xcmod
```

---

## API 参考

### MOD 商店 API

#### GET `/api/mod-store/catalog`
获取 MOD 目录

**响应示例：**
```json
{
  "success": true,
  "data": {
    "installed": [...],
    "available": [...],
    "indexed_count": 10
  }
}
```

#### POST `/api/mod-store/upload`
上传 MOD 包

**请求参数：**
- `file` (FormData): MOD 包文件
- `activate` (boolean): 是否立即激活
- `verify_signature` (boolean): 是否验证签名

**响应示例：**
```json
{
  "success": true,
  "message": "MOD my-mod v1.0.0 上传成功",
  "data": {
    "id": "my-mod",
    "name": "我的 MOD",
    "version": "1.0.0"
  }
}
```

#### POST `/api/mod-store/install`
安装 MOD

**请求参数：**
- `package_file` (string): MOD 包文件名
- `activate` (boolean): 是否激活
- `verify_signature` (boolean): 是否验证签名

#### POST `/api/mod-store/uninstall`
卸载 MOD

**请求参数：**
- `mod_id` (string): MOD ID
- `remove_files` (boolean): 是否删除文件

#### POST `/api/mod-store/update`
更新 MOD

**请求参数：**
- `mod_id` (string): MOD ID
- `package_file` (string): MOD 包文件名

#### GET `/api/mod-store/search`
搜索 MOD

**请求参数：**
- `q` (string): 搜索关键词
- `author` (string): 作者
- `installed` (boolean): 是否已安装
- `limit` (integer): 返回数量限制

**响应示例：**
```json
{
  "success": true,
  "data": [...],
  "count": 5
}
```

#### GET `/api/mod-store/popular`
获取热门 MOD

**请求参数：**
- `limit` (integer): 返回数量

#### GET `/api/mod-store/recent`
获取最新 MOD

**请求参数：**
- `limit` (integer): 返回数量

#### GET `/api/mod-store/mod/{mod_id}/details`
获取 MOD 详情

**响应示例：**
```json
{
  "success": true,
  "data": {
    "id": "my-mod",
    "name": "我的 MOD",
    "version": "1.0.0",
    "statistics": {
      "total_downloads": 100,
      "avg_rating": 4.5,
      "rating_count": 20
    },
    "ratings": [...]
  }
}
```

#### POST `/api/mod-store/mod/{mod_id}/rate`
评分 MOD

**请求参数：**
- `rating` (integer): 评分 (1-5)
- `comment` (string): 评论
- `user_id` (string): 用户 ID

#### GET `/api/mod-store/updates`
检查可用更新

**响应示例：**
```json
{
  "success": true,
  "data": {
    "updates_available": [
      {
        "mod_id": "my-mod",
        "current_version": "1.0.0",
        "new_version": "1.1.0",
        "package_file": "my-mod-1.1.0.xcmod"
      }
    ],
    "count": 1
  }
}
```

#### GET `/api/mod-store/dependencies`
解析依赖关系

**请求参数：**
- `package_file` (string): MOD 包文件名

**响应示例：**
```json
{
  "success": true,
  "data": {
    "mod_id": "my-mod",
    "dependencies": ["xcagi", "other-mod"],
    "satisfied": [
      {"id": "xcagi", "version_spec": ">=5.0.0", "status": "satisfied"}
    ],
    "missing": [
      {"id": "other-mod", "version_spec": ">=1.0.0", "status": "missing"}
    ],
    "can_install": false
  }
}
```

---

## 前端使用

### 组件导入

```vue
<template>
  <div>
    <ModStore />
  </div>
</template>

<script>
import ModStore from '@/views/ModStore.vue';

export default {
  components: {
    ModStore,
  },
};
</script>
```

### 使用 API Client

```typescript
import {
  getModCatalog,
  installMod,
  uninstallMod,
  searchMods,
} from '@/api/modStore';

// 获取 MOD 目录
const catalog = await getModCatalog();

// 搜索 MOD
const results = await searchMods('keyword');

// 安装 MOD
await installMod('my-mod-1.0.0.xcmod');

// 卸载 MOD
await uninstallMod('my-mod');
```

### 使用 Pinia Store

```typescript
import { useModStoreStore } from '@/stores/modStore';

const modStore = useModStoreStore();

// 加载目录
await modStore.loadCatalog();

// 安装 MOD
await modStore.installModAction('my-mod-1.0.0.xcmod');

// 获取已安装 MOD
const installed = modStore.installedMods;
```

---

## 最佳实践

### MOD 开发

1. **遵循语义化版本** - 使用 `MAJOR.MINOR.PATCH` 格式
2. **提供完整描述** - 在 manifest.json 中详细描述功能
3. **声明依赖** - 明确列出所有依赖项
4. **错误处理** - 妥善处理异常，避免影响主系统
5. **日志记录** - 使用 logging 模块记录关键操作

### 安全性

1. **签名验证** - 生产环境启用签名验证
2. **权限控制** - 限制 MOD 的系统访问权限
3. **沙箱测试** - 在隔离环境测试新 MOD
4. **代码审查** - 上架前进行人工审核

### 性能优化

1. **懒加载** - 按需加载 MOD 资源
2. **缓存索引** - 定期重建索引而非每次扫描
3. **异步处理** - 安装/卸载使用异步任务
4. **分页查询** - 大量 MOD 时使用分页

### 版本管理

1. **向后兼容** - 尽量保持 API 兼容
2. **变更日志** - 记录每个版本的变更
3. **回滚机制** - 支持快速回滚到旧版本
4. **更新通知** - 及时通知用户可用更新

---

## 故障排查

### 常见问题

**Q: MOD 无法安装**
- 检查依赖是否满足
- 验证 MOD 包完整性
- 查看后端日志

**Q: 搜索不工作**
- 检查索引是否建立
- 调用 `/api/mod-store/index/rebuild` 重建索引

**Q: 前端无法连接**
- 确认后端服务运行
- 检查 API 路由配置
- 查看浏览器控制台错误

### 日志位置

- 后端日志：`logs/xcagi.log`
- MOD 安装日志：查看控制台输出
- 前端错误：浏览器开发者工具

---

## 贡献指南

欢迎贡献 MOD 商店系统！

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

---

## 许可证

MIT License

---

## 联系方式

- 技术支持：support@example.com
- 问题反馈：GitHub Issues
