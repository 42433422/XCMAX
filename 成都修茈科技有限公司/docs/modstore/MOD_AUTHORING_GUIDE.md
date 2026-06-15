# XCAGI MOD 作者指南（Authoring Guide）

> 面向：要为 XCAGI 开发 / 打包 / 维护 **Mod**（业务功能扩展包）的开发者。
> 版本对齐：XCAGI 6.0（Neuro-DDD + FastAPI 主栈，2026-04-20 结构重整后）。
> 配套：`app/mod_sdk/`（Mod 面向主程的唯一契约层）+ `scripts/dev/check_mod_import_boundaries.py`（硬边界 lint）。

---

## 目录

1. [是什么 / 不是什么](#1-是什么--不是什么)
2. [核心术语](#2-核心术语)
3. [目录布局硬规则](#3-目录布局硬规则)
4. `[manifest.json` 字段参考](#4-manifestjson-字段参考)
5. [后端契约：路由、生命周期、动态加载](#5-后端契约路由生命周期动态加载)
6. [SDK 层：`app.mod_sdk.`* 完整地图](#6-sdk-层appmod_sdk-完整地图)
7. [硬边界 Lint：什么不能 import](#7-硬边界-lint什么不能-import)
8. [前端：routes / menu / menu_overrides](#8-前端routes--menu--menu_overrides)
9. [Hook：订阅主程业务事件](#9-hook订阅主程业务事件)
10. [Comms：Mod 间点对点调用](#10-commsmod-间点对点调用)
11. [Workflow Employees：声明工作流员工](#11-workflow-employees声明工作流员工)
12. [静态资源：data / config / resources](#12-静态资源data--config--resources)
13. [依赖与版本](#13-依赖与版本)
14. [Artifact 类型：mod / employee_pack / bundle](#14-artifact-类型mod--employee_pack--bundle)
15. [生命周期全貌](#15-生命周期全貌)
16. [打包、签名、安装](#16-打包签名安装)
17. [测试与冒烟](#17-测试与冒烟)
18. [从零到上架的工作流](#18-从零到上架的工作流)
19. [常见反模式](#19-常见反模式)
20. [参考实现](#20-参考实现)

---

## 1. 是什么 / 不是什么

**Mod 是** —— XCAGI 运行时可插拔的**业务能力单元**，一个 Mod 一个文件夹，内部带自己的 `manifest.json` + 后端路由 + 前端路由/菜单 + 数据/配置 + 可选的 hook 订阅与跨 Mod 通信通道。发现机制是纯 **opendir**：解压到 `mods/<mod_id>/` 即可，无需修改主程代码。

**Mod 不是** ——

- 不是 Plugin 热补丁：禁止 monkey-patch 主程、禁止覆盖 `app.`* 任何符号。
- 不是共享库：`mods/` 下的模块**不应**被主程 `import`；关系始终是「主程暴露 SDK → Mod 消费 SDK」。
- 不是 Flask 插件：Mod 后端**只出** FastAPI `APIRouter`，不再有 `Blueprint`。

---

## 2. 核心术语


| 术语                                             | 定义                                                               | 物理位置                                   |
| ---------------------------------------------- | ---------------------------------------------------------------- | -------------------------------------- |
| **Mod**（`artifact: "mod"`，默认）                  | 可装可卸的业务扩展单元；带路由、菜单、生命周期钩子。                                       | `mods/<mod_id>/`                       |
| **Employee Pack**（`artifact: "employee_pack"`） | 全局 AI 员工包，只声明 **一个** `workflow_employee`，不带路由也不带前端菜单。            | `mods/_employees/<pack_id>/`           |
| **Bundle**（`artifact: "bundle"`）               | 元包：打包多个 Mod / Employee Pack 的组合安装，本体不含业务代码。                      | `mods/<bundle_id>/` 仅含 manifest        |
| **Workflow Employee**（工作流员工）                   | 声明式 AI 员工；前端工作流面板按清单生成控制卡，Mod 后端提供轮询 / 启停接口。                     | 在 manifest 的 `workflow_employees[]` 声明 |
| **Hook**                                       | 主程广播的业务事件（如 `shipment.created`、`product.imported`），多个订阅者，返回值被忽略。 | `app.infrastructure.mods.hooks`        |
| **Comms**                                      | Mod 间点对点同步 RPC（指定目标 Mod + 通道），有返回值。                              | `app.mod_sdk.comms`                    |
| **ModManager**                                 | 发现、解析、加载、卸载 Mod 的单例；扫根目录由 `XCAGI_MODS_ROOT` 或默认算法决定。             | `app.infrastructure.mods.mod_manager`  |
| **SDK 层**                                      | Mod 对主程的**唯一合法 import 面**。                                       | `app/mod_sdk/`                         |


---

## 3. 目录布局硬规则

一个 Mod 必须落在 `mods/<mod_id>/` 下，**文件夹名应与 `manifest.id` 一致**（ModManager 用目录名定位、用 manifest 内的 id 作为对外 id；两者一致能避免混淆）。

```
mods/<mod_id>/
├── manifest.json              # 必须。Mod 的身份 + 契约声明
├── backend/
│   ├── __init__.py            # 必须（即使空），声明为包
│   ├── blueprints.py          # 约定命名：后端入口（见 §5）
│   ├── services.py            # 推荐：业务代码
│   ├── <任意子模块>.py         # 推荐：按业务域拆分
│   └── <sub_pkg>/             # 允许子包
├── frontend/
│   ├── routes.js              # Vue Router 路由表 + 菜单项导出
│   └── views/*.vue            # 页面组件
├── data/                      # 可选：随包分发的只读数据（JSON/YAML/CSV）
├── config/                    # 可选：可被主程读取的配置覆盖
└── <其它资源>                  # 文档、图标、示例……
```

### 硬规则

1. **文件名 `manifest.json` 固定**，位于 Mod 根。未提供或 JSON 解析失败 → 加载跳过，不中断主程。
2. `**backend/__init__.py` 必须存在**（可以为空）。否则 `import_mod_backend_py` 能绕过 Python 包机制工作，但同 Mod 内子模块相对 import 会失败。
3. `**manifest.backend.entry`（默认 `"blueprints"`）指向 `backend/<entry>.py`**；该文件**必须**导出下列之一：
  - 推荐：`register_fastapi_routes(app, mod_id: str) -> None`
  - 废弃：`register_blueprints(app, mod_id: str)`（Flask 时代遗留，**禁止新 Mod 使用**）
4. **同名文件别怕冲突**：两个 Mod 都叫 `services.py` 不会相互覆盖，ModManager 用 `importlib` 按独立 spec name `_xcagi_mod_<mod_id>_<stem>` 加载；详见 §15。
5. **文件夹内不允许再嵌套同级 Mod**。Bundle 有自己的组合方式（§14），不走嵌套目录。

---

## 4. `manifest.json` 字段参考

以下字段表对齐 `app/infrastructure/mods/manifest.py::ModMetadata`。**所有顶层字段**：


| 字段                   | 类型     | 必填  | 说明                                                                                                       |
| -------------------- | ------ | --- | -------------------------------------------------------------------------------------------------------- |
| `id`                 | string | ✅   | Mod 全局唯一 id；建议小写 kebab-case，与文件夹同名。                                                                      |
| `name`               | string | ✅   | 显示名（中英文均可）。                                                                                              |
| `version`            | string | ✅   | SemVer，如 `"1.0.0"`。                                                                                      |
| `author`             | string | –   | 作者/团队。                                                                                                   |
| `description`        | string | –   | 一句话描述。                                                                                                   |
| `artifact`           | string | –   | `"mod"` / `"employee_pack"` / `"bundle"`；默认 `"mod"`。另见 `kind`（历史别名）。                                     |
| `primary`            | bool   | –   | 是否为**主 Mod**。同时启用的主 Mod 数量应为 1；前端侧边栏会把主 Mod 的菜单置于第一位。                                                    |
| `dependencies`       | object | –   | `{dep_id: version_spec}`；`xcagi` 为宿主版本约束；其它 id 代表必须同装的其它 Mod。                                            |
| `backend`            | object | ✅   | 后端入口约定，见下表。                                                                                              |
| `frontend`           | object | –   | 前端路由 + 菜单声明，见 §8。                                                                                        |
| `config`             | object | –   | 见下表。                                                                                                     |
| `hooks`              | object | –   | `{event_name: "relative.module.attr"}`；主程触发对应事件时同步回调。详见 §9。                                              |
| `comms`              | object | –   | `{ "exports": ["<channel>", ...] }`；**仅作声明用途**，运行时通过 `mod_sdk.comms.get_mod_comms().register(...)` 真正注册。 |
| `workflow_employees` | array  | –   | 声明的工作流员工清单，见 §11。                                                                                        |
| `bundle`             | object | –   | 仅 `artifact=="bundle"` 时有意义；包装其它 Mod 的 id 列表。                                                            |


### `backend`

```jsonc
"backend": {
  "entry": "blueprints",   // => backend/blueprints.py（不含 .py）
  "init":  "mod_init"      // entry 模块里的生命周期初始化函数；可选
}
```

`entry` 模块里的以下函数会被 ModManager 按顺序查找调用：


| 函数名                                    | 时机                             | 必须？     |
| -------------------------------------- | ------------------------------ | ------- |
| `register_fastapi_routes(app, mod_id)` | 主应用启动、`load_mod_routes` 阶段     | **推荐**  |
| `register_blueprints(app, mod_id)`     | 同上（仅为向下兼容保留的 no-op，Flask 时代遗留） | ❌ 新代码禁止 |
| `<init>()`（默认叫 `mod_init`）             | `load_mod` 注册元数据完成后立即调用        | 可选      |


### `frontend`

见 §8，字段 `routes`、`menu`、`menu_overrides`。

### `config`

```jsonc
"config": {
  "industry_overrides": "config/industry_overrides.yaml"
}
```

`industry_overrides` 指向**相对本 Mod 根**的 YAML 文件，主程用于叠加行业定制覆盖。

### `hooks`

```jsonc
"hooks": {
  "shipment.created":  "services.on_shipment_created",
  "product.imported":  "services.on_product_imported"
}
```

**Handler spec 语法**：`<module>.<attr>`，其中 `<module>` 是 Mod 的 `backend/` 下的模块名（相对 backend/，**不要**带 `backend.` 前缀；ModManager 会自动剥离）。

### `comms`

```jsonc
"comms": { "exports": ["mod_info", "pricing.quote"] }
```

仅作**意图声明**（供 MODstore / 审计展示），不代替代码侧的 `register()`。建议通道名用「点分层」（`inventory.snapshot`、`pricing.quote`）避免冲突。

### 最小可用 manifest 示例

```json
{
  "id": "my-mod",
  "name": "我的 Mod",
  "version": "1.0.0",
  "author": "ACME",
  "description": "示例能力：回显 hello",
  "primary": false,
  "dependencies": { "xcagi": ">=6.0.0" },
  "backend": { "entry": "blueprints", "init": "mod_init" },
  "frontend": {
    "routes": "frontend/routes",
    "menu": [
      { "id": "my-home", "label": "我的 Mod", "icon": "fa-cube", "path": "/my-mod" }
    ]
  },
  "hooks": {},
  "comms": { "exports": [] }
}
```

---

## 5. 后端契约：路由、生命周期、动态加载

### 5.1 路由注册（推荐形态）

```python
# mods/my-mod/backend/blueprints.py
from __future__ import annotations

import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)


def register_fastapi_routes(app, mod_id: str) -> None:
    """主进程 FastAPI：Mod HTTP 面。

    路由前缀强约定为 ``/api/mod/<mod_id>``；tags=[f"mod-{mod_id}"] 便于 OpenAPI 聚合。
    """
    router = APIRouter(prefix=f"/api/mod/{mod_id}", tags=[f"mod-{mod_id}"])

    @router.get("/hello")
    def hello():
        return {"success": True, "data": {"message": f"Hello from {mod_id}"}}

    app.include_router(router)
    logger.info("my-mod routes registered: %s", mod_id)


def mod_init():
    """元数据注册成功后立即调用。此处做 comms 注册、启动后台任务等。"""
    logger.info("my-mod initialized")
```

**契约**：

- **前缀必须是 `/api/mod/<mod_id>/...`**。不要占用主程业务前缀（`/api/products/...` 等），否则 OpenAPI 与权限中间件会把你算作主程。
- `**register_fastapi_routes` 可以多次安全调用**（需要幂等：`APIRouter` 新建即可）；`load_mod_routes` 一次性注册，但 `ensure_mods_loaded` 存在补偿重试路径。
- **不要在模块顶层做副作用**（连 DB、起线程）。副作用一律放进 `mod_init()` 或路由的 lazy init。模块顶层**只做 import + 函数定义**。

### 5.2 同 Mod 内动态加载

如果 `blueprints.py` 需要加载同 Mod 的另一个 `.py` 作为模块（例如大型电话业务员：`backend/services.py` / `backend/event_bus.py`），**不要**用裸 `import`（Mod 不在 sys.path 上，会失败）。用 SDK 提供的文件路径式加载器：

```python
from app.mod_sdk.mods_bus import import_mod_backend_py

mod_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 本 Mod 根
services_mod = import_mod_backend_py(mod_path, "my-mod", "services")
manager = services_mod.get_something()
```

`import_mod_backend_py` 会把 `<mod_path>/backend/<stem>.py` 按独立 `sys.modules` 入口 `_xcagi_mod_<mod_id>_<stem>` 加载，多个 Mod 都有 `services.py` 不会相互覆盖。

### 5.3 生命周期钩子

```python
def mod_init():
    """在 manifest 元数据 registry 注册成功后调用一次；失败不会阻塞主程启动。

    用于：
      - 向 comms 注册端点
      - 预加载模型 / 连接池
      - 注册 hook 订阅（若 manifest.hooks 已声明则自动订阅；这里可做额外手工订阅）
    """
```

**禁止**：

- ❌ 在 `mod_init` 里 `sys.exit` / 阻塞式等待外部服务
- ❌ `import` 主程任何非 `app.mod_sdk.`* 的模块（§7 边界）
- ❌ 注册路由（路由统一走 `register_fastapi_routes`）

---

## 6. SDK 层：`app.mod_sdk.`* 完整地图

`app/mod_sdk/` 是主程对 Mod 的**唯一稳定契约层**。主程内部任何重构只要保 `mod_sdk.`* 的符号不变，Mod 不会被打爆。


| SDK 子模块                  | 导出符号                                                                               | 用途                                             |
| ------------------------ | ---------------------------------------------------------------------------------- | ---------------------------------------------- |
| `app.mod_sdk.comms`      | `get_caller_mod_id`, `get_mod_comms`                                               | Mod 间点对点 RPC，见 §10                             |
| `app.mod_sdk.mods_bus`   | `import_mod_backend_py`                                                            | 动态加载同 Mod 内 `backend/<stem>.py`，见 §5.2         |
| `app.mod_sdk.db`         | `SessionLocal`                                                                     | SQLAlchemy 会话工厂，`SessionLocal()` → ORM Session |
| `app.mod_sdk.db_models`  | `PurchaseUnit`（渐次扩展）                                                               | 受限 ORM 直通，**优先**走 `mod_sdk.services` 高层方法      |
| `app.mod_sdk.services`   | `get_products_service`, `get_ai_chat_app_service`, `get_unified_intent_recognizer` | 主程高层服务入口                                       |
| `app.mod_sdk.tts`        | `synthesize_to_data_uri`                                                           | TTS 合成，返回 `data:audio/...;base64,...` URI      |
| `app.mod_sdk.state`      | `read_client_mods_off_state`                                                       | 前端是否启用了「原版模式」（关闭所有 Mod 扩展）                     |
| `app.mod_sdk.ai_helpers` | `format_money`, `safe_float`                                                       | 金额 / 数值格式化                                     |
| `app.mod_sdk.workspace`  | `resolve_safe_workspace_relpath`                                                   | 工作区相对路径安全解析，防越狱                                |
| `app.mod_sdk.attendance` | `convert_attendance_file`, `attendance_workspace_root`                             | 考勤转换（太阳鸟 PRO 专用，未来任务 B 会把实现归位回 mod）            |


### 使用模式

```python
# 数据库
from app.mod_sdk.db import SessionLocal
from app.mod_sdk.db_models import PurchaseUnit

db = SessionLocal()
try:
    unit = db.query(PurchaseUnit).filter(PurchaseUnit.name == "客户A").first()
finally:
    db.close()

# 高层服务
from app.mod_sdk.services import get_products_service, get_unified_intent_recognizer

products = get_products_service().get_by_model_number("9803")
intents  = get_unified_intent_recognizer().recognize("帮我打印发货单")

# TTS
from app.mod_sdk.tts import synthesize_to_data_uri
data_uri = synthesize_to_data_uri("你好，请稍等", voice="zh-CN-XiaoxiaoNeural")

# 客户端开关：长驻任务启动前检查
from app.mod_sdk.state import read_client_mods_off_state
if read_client_mods_off_state():
    logger.info("client requested mods-off; skipping start")
    return False
```

### 新增 SDK 符号的流程

`app.mod_sdk.*` 的可见面由各子模块的 `__all__` 锁定。要暴露新符号：

1. 在主程中确认该能力有稳定的公共入口（而非私有函数）。
2. 在对应 SDK 子模块里加一行 `from app.<内部模块> import <符号>` 并加入 `__all__`。
3. 在 `app/mod_sdk/__init__.py` 的子模块表里补上说明。
4. 运行 `scripts/dev/smoke_all.py` 确保无回归。

---

## 7. 硬边界 Lint：什么不能 import

Mod 目录下所有 `.py` 文件通过 `**scripts/dev/check_mod_import_boundaries.py**` 静态 AST 扫描：

### 允许前缀

- `app.mod_sdk` 及其所有子模块
- Mod 自身相对 import（`from .services import ...`）

### 禁止前缀

- 其它任何 `app.*`（包括 `app.services.*`、`app.db.*`、`app.routes.*`、`app.application.*`、`app.bootstrap`、`app.utils.*` 等）
- 任何 `backend.*`（compat shim 层，内部使用）

### 被扫路径

```
mods/**/*.py
XCAGI/mods/**/*.py
XCAGI/AI手机电话功能包/backend/**/*.py
```

### 如何运行

```bash
python scripts/dev/check_mod_import_boundaries.py
# 违规时退出码为 1

# JSON 输出（供 CI 解析）
python scripts/dev/check_mod_import_boundaries.py --json
```

违规示例输出：

```
[mod-boundary] 2 VIOLATION(S):
  mods/my-mod/backend/services.py:12  from app.services.tts_service import synthesize_to_data_uri
  mods/my-mod/backend/services.py:45  from app.bootstrap import get_products_service
```

---

## 8. 前端：routes / menu / menu_overrides

### 8.1 `frontend/routes.js`

必须 export 两个具名符号（命名惯例由宿主前端框架消费）：

```javascript
// mods/my-mod/frontend/routes.js
const myModRoutes = [
  {
    path: '/my-mod',
    name: 'my-mod-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '我的 Mod', mod: 'my-mod' }   // meta.mod 必填，用于权限 / 路由归属
  },
  {
    path: '/my-mod/details/:id',
    name: 'my-mod-detail',
    component: () => import('./views/DetailView.vue'),
    meta: { title: '详情', mod: 'my-mod' }
  }
];

const myModMenu = [
  { id: 'my-mod-home', label: '我的 Mod', icon: 'fa-cube', path: '/my-mod' }
];

export { myModRoutes, myModMenu };
```

### 8.2 `manifest.frontend.menu[]`

每条菜单项字段：


| 字段      | 类型     | 必填  | 说明                                   |
| ------- | ------ | --- | ------------------------------------ |
| `id`    | string | ✅   | 菜单项唯一 id，前端用于 state 持久化。             |
| `label` | string | ✅   | 显示名。                                 |
| `icon`  | string | –   | FontAwesome class（不含 `fa-` 是错的，要写全）。 |
| `path`  | string | ✅   | 与 routes.js 中的 `path` 一致，前端路由跳转目标。   |


### 8.3 `manifest.frontend.menu_overrides[]`

覆盖主程侧边栏已有菜单项的 label / 图标（例：`taiyangniao-pro` 把「产品」改称「人员」、「客户」改称「部门」）：

```jsonc
"menu_overrides": [
  { "key": "products",  "label": "人员管理" },
  { "key": "customers", "label": "部门管理" }
]
```

`key` 指主程内置菜单项 id。ModManager 也接受 object 形态（`{ products: { label: "人员管理" } }`），解析时会规范化为上面的数组形态。

---

## 9. Hook：订阅主程业务事件

Hook 是主程→订阅者的**单向广播**：多订阅者，顺序同步调用，handler 抛出异常被吞并记 error 日志（不影响主程业务路径）。

### 9.1 当前已触发的事件


| 事件名                | 触发位置                                               | 参数（kwargs）                       |
| ------------------ | -------------------------------------------------- | -------------------------------- |
| `shipment.created` | `app/application/shipment_app_service.py` 成功创建发货单后 | `shipment=<Shipment>`            |
| `product.imported` | `app/services/product_import_service.py` 批量导入产品成功后 | `count=<int>`, `products=<list>` |


> 要触发自己的事件的主程工程师：`from app.infrastructure.mods.hooks import trigger; trigger("my.event", payload=...)`。
> 当前端处于「原版模式」（`read_client_mods_off_state() == True`）时，**所有 hook 触发都会被短路**，不会回调订阅者。

### 9.2 声明与实现

**Manifest 声明**：

```jsonc
"hooks": {
  "shipment.created": "services.on_shipment_created",
  "product.imported": "services.on_product_imported"
}
```

**实现**：

```python
# mods/my-mod/backend/services.py
def on_shipment_created(*, shipment):
    # shipment 是主程的领域对象，读它的属性即可
    print(f"my-mod saw shipment #{shipment.id}")

def on_product_imported(*, count, products):
    print(f"my-mod saw {count} products imported")
```

**约定**：

- handler **只接 kwargs**；忽略位置参数对未来兼容更友好。
- handler **不应抛异常**；要让主程感知的异常请 log 后吞掉。
- handler **绝不回写主程状态**；要改主程数据请发 comms 或走 HTTP。

### 9.3 动态订阅（不用 manifest）

少见但合法。在 `mod_init` 里：

```python
from app.infrastructure.mods.hooks import subscribe  # 这个是主程契约，后续会搬到 app.mod_sdk.hooks

def on_event(**kw):
    ...

def mod_init():
    subscribe("my.custom.event", on_event)
```

> `app.infrastructure.mods.hooks` 暂未经由 SDK 暴露；若未来 boundary lint 加严，需要一并导出到 `app.mod_sdk.hooks`。当前只要你的 manifest 里有声明就**不必用动态订阅**。

---

## 10. Comms：Mod 间点对点调用

Comms 是同步 RPC，指定「目标 Mod + 通道名」，有返回值。

### 10.1 在 A Mod 注册通道

```python
# mods/a-mod/backend/blueprints.py
from app.mod_sdk.comms import get_caller_mod_id, get_mod_comms


def _ping(**kwargs):
    return {
        "pong": True,
        "from": "a-mod",
        "caller_mod": get_caller_mod_id(),  # 对端 Mod id；未设上下文时 None
        "kwargs": kwargs,
    }


def mod_init():
    get_mod_comms().register("a-mod", "ping", _ping, replace=True)
```

### 10.2 在 B Mod 调用

```python
# mods/b-mod/backend/services.py
from app.mod_sdk.comms import get_mod_comms

def do():
    result = get_mod_comms().call(
        source_mod_id="b-mod",   # 本 Mod 的 id
        target_mod_id="a-mod",
        channel="ping",
        hello="world",
    )
    return result  # {"pong": True, "from": "a-mod", "caller_mod": "b-mod", "kwargs": {"hello": "world"}}
```

### 10.3 API 契约


| 方法                                                     | 行为                                                    |
| ------------------------------------------------------ | ----------------------------------------------------- |
| `register(mod_id, channel, handler, *, replace=False)` | 注册通道；已存在且 `replace=False` 时抛 `ModCommsConflictError`。 |
| `unregister(mod_id, channel)`                          | 注销单个通道。                                               |
| `unregister_all(mod_id)`                               | 清理某 Mod 所有通道（卸载时用）。                                   |
| `call(source, target, channel, *args, **kwargs)`       | 同步调用并返回；未注册时抛 `ModCommsNotFoundError`。                |
| `has_handler(target, channel)`                         | 不抛异常的存在性检查。                                           |
| `list_endpoints()`                                     | 枚举所有已注册端点（管理/调试用）。                                    |


**约定**：

- **通道名用点分层**：`inventory.snapshot`、`pricing.quote`、`report.export`。避免 `get`、`data` 这种通用词。
- **参数与返回值必须是可 JSON 序列化的 dict / list / 基础类型**。不要传领域对象或 ORM 模型（未来可能改造为跨进程通信）。
- **不要在 comms handler 里做长耗时操作**（> 1s）；Comms 是同步阻塞的。长任务让调用方轮询。

### 10.4 相关 manifest 字段

`comms.exports[]` 仅作声明，运行时必须 `register()` 才算数。建议**声明与注册保持一致**，供 MODstore 审计。

---

## 11. Workflow Employees：声明工作流员工

Workflow Employee 是**前端工作流面板**生成控制卡的元数据。每个工作流员工对应前端一个面板卡片，面板里出现启停按钮、状态轮询、步骤进度。

### 11.1 字段规范

```jsonc
"workflow_employees": [
  {
    "id":                         "wechat_phone",       // 必填；员工 id，全局唯一
    "label":                      "微信电话对接业务员",   // 必填；卡片标题
    "panel_title":                "工作流 · 微信电话对接业务员",  // 可选；面板大标题
    "panel_summary":              "副窗启用后 → Win32 监控微信来电 → 自动接听 → 采集 → ASR → 意图 → TTS → VB-Cable 回灌。",
    "phone_agent_base_path":      "phone-agent",        // 可选；电话类员工专用：相对本 Mod /api/mod/<id>/ 的子路径
    "workflow_placeholder":       false                 // 可选；true 表示「占位员工」，只展示卡片不启动后端任务
  }
]
```

已知约定字段（将被前端 / `employee_registry` 消费）：


| 字段                              | 语义                                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `id`                            | 员工 id。                                                                                                                |
| `label`                         | 卡片标题。                                                                                                                 |
| `panel_title` / `panel_summary` | 面板顶部文案。                                                                                                               |
| `phone_agent_base_path`         | 若该员工是「电话业务员」类型，Mod 须在 `/api/mod/<mod_id>/<phone_agent_base_path>/{status,start,stop,statu}` 下提供 4 条路由（`statu` 为容错别名）。 |
| `workflow_placeholder`          | `true` 时前端渲染卡片但不触发后端；常见于「待接入」状态。                                                                                      |
| 任意自定义字段                         | 原样保留透传到前端；按 `id` 前缀约定使用。                                                                                              |


### 11.2 后端配套接口（电话业务员类）

若 `phone_agent_base_path` 出现，推荐 Mod 在对应前缀下提供：


| 方法     | 路径                                  | 行为                                                                          |
| ------ | ----------------------------------- | --------------------------------------------------------------------------- |
| `GET`  | `/phone-agent/status?channel=wechat | adb`                                                                        |
| `POST` | `/phone-agent/start`                | 启动；失败返回 `{"success": false, "message": "..."}`（**HTTP 仍为 200**，业务失败不用 5xx）。 |
| `POST` | `/phone-agent/stop`                 | 停止。                                                                         |
| `GET`  | `/phone-agent/statu`                | 对前端历史拼写错误（少写 `s`）的容错别名。                                                     |


**参考实现**：`mods/sz-qsm-pro/backend/blueprints.py` 的 `register_fastapi_routes`。

### 11.3 Employee Pack（全局员工包）

若你只想发一个 AI 员工（不带菜单、不带路由），把 artifact 设为 `employee_pack`：

```jsonc
{
  "id":       "accountant-ai",
  "name":     "财务 AI 员工",
  "version":  "1.0.0",
  "artifact": "employee_pack",
  "scope":    "global",
  "employee": {
    "id":    "accountant",
    "label": "AI 财务",
    "capabilities": ["invoice.parse", "report.monthly"]
  }
}
```

安装目的地是 `mods/_employees/<pack_id>/`（**不是**普通 `mods/<pack_id>/`）。

---

## 12. 静态资源：data / config / resources


| 目录                 | 用途                                                        | 如何读取                                                |
| ------------------ | --------------------------------------------------------- | --------------------------------------------------- |
| `<mod>/data/`      | 随包分发的只读数据。                                                | `Path(__file__).parent.parent / "data" / "...json"` |
| `<mod>/config/`    | YAML / JSON 配置；`manifest.config.industry_overrides` 指向此处。 | 主程通过 `manifest.config_overrides` 路径加载。              |
| `<mod>/resources/` | 静态资源（图标、示例文件、安装指南 md）。                                    | 同 data，Mod 自取。                                      |


**写入约定**：Mod **不应**向自身目录写入运行时产物。需要持久化 → 用 `app.mod_sdk.db` 写数据库；需要临时文件 → 用系统 temp dir（Python `tempfile`）。

---

## 13. 依赖与版本

### 13.1 宿主版本

```jsonc
"dependencies": { "xcagi": ">=6.0.0" }
```

当前仅支持 `>=<version>` 形式。由 `app.infrastructure.mods.manifest._check_xcagi_version` 校验；宿主常量 `current_version` 编码在 manifest.py 中。升级 XCAGI 时请同步该常量。

### 13.2 Mod 间依赖

```jsonc
"dependencies": {
  "xcagi":           ">=6.0.0",
  "common-kit-mod":  ">=1.2.0"
}
```

目前 Mod 间依赖只做**已加载性**与**版本字符串**检查；不做强制的拓扑排序（加载顺序按 `os.listdir` 返回序）。要确保依赖先加载：

- 把必要依赖**打成 Bundle**（§14），发行时一起分发；
- 或在你的 `mod_init` / 路由处理里对 `ModManager.scan_mods()` 做 defensive check。

### 13.3 Python 包依赖

如果你的 Mod 依赖 PyPI 包（如 `faster-whisper`、`miniaudio`），**不要**让主程 `requirements.txt` 随你膨胀。

两条路：

1. **主 Mod**（`primary: true`）可与主程合并部署 → 把依赖写进主 `requirements.txt`（当前 `sz-qsm-pro` 走这条）。
2. **发行 Mod** → 在 Mod 根放 `requirements-<mod_id>.txt`（如 `requirements-phone-template.txt`），约定由安装流程在安装时 pip install。主程启动路径不默认执行此文件。

---

## 14. Artifact 类型：mod / employee_pack / bundle


| artifact        | 用途         | 安装目的地                   | 典型内容                                        |
| --------------- | ---------- | ----------------------- | ------------------------------------------- |
| `mod`           | 业务扩展（默认）。  | `mods/<id>/`            | backend + frontend + hooks + comms          |
| `employee_pack` | 全局 AI 员工包。 | `mods/_employees/<id>/` | 只含 `manifest.json`（含 `employee` 子对象）        |
| `bundle`        | 元包，组合安装。   | `mods/<id>/` 仅 manifest | `manifest.bundle.items[]` 列出子包 id + version |


Bundle 示例：

```jsonc
{
  "id":       "retail-starter-bundle",
  "artifact": "bundle",
  "name":     "零售起步套件",
  "version":  "1.0.0",
  "bundle": {
    "items": [
      { "id": "common-kit-mod", "version": ">=1.0.0", "artifact": "mod" },
      { "id": "accountant-ai",  "version": ">=1.0.0", "artifact": "employee_pack" }
    ]
  }
}
```

---

## 15. 生命周期全貌

```
┌──────────────────────────── 启动期 ─────────────────────────────┐
│                                                                 │
│   get_fastapi_app()                                             │
│       │                                                         │
│       ├── register_all_routes(app)  ← app/fastapi_routes/       │
│       │                                                         │
│       └── ModManager.load_all_mods() + load_mod_routes(app, mm) │
│              │                                                  │
│              ├── scan_mods()  ── os.listdir(mods_root)          │
│              │     │                                            │
│              │     └── parse_manifest(<mod_path>)  ← manifest.py│
│              │                                                  │
│              ├── for each ModMetadata:                          │
│              │     load_mod(mod_id):                            │
│              │        ├── validate_dependencies                 │
│              │        ├── register metadata → registry          │
│              │        ├── import_mod_backend_py(entry, mod_id)  │
│              │        ├── _register_mod_hooks(manifest.hooks)   │
│              │        └── call <init>()  (e.g. mod_init)        │
│              │                                                  │
│              └── for each loaded mod:                           │
│                    register_fastapi_routes(app, mod_id)         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────── 运行期 ─────────────────────────────────┐
│                                                                 │
│   HTTP request → FastAPI router → Mod route handler             │
│                                                                 │
│   主程业务事件 → trigger("shipment.created", ...)                │
│                       │                                         │
│                       └─► 每个订阅的 Mod handler 被同步回调       │
│                                                                 │
│   Mod A → get_mod_comms().call(src, tgt, channel, ...)          │
│                       │                                         │
│                       └─► Mod B 同步返回                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌───────────────────── 卸载期（运行时可选） ──────────────────────┐
│                                                                 │
│   ModManager.uninstall_mod(mod_id):                             │
│       ├── sys.modules 清理 _xcagi_mod_<mod_id>_* 前缀            │
│       ├── hooks unsubscribe（按 handler 清理）                   │
│       ├── comms.unregister_all(mod_id)                          │
│       └── 从 registry 移除元数据                                  │
│                                                                 │
│   * 路由卸载需要 FastAPI 重新构建应用；建议通过                   │
│     "restart required" 标志 + 前端提示用户手动重启。              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 发现 mods 根的策略（优先级由高到低）

见 `app/infrastructure/mods/mod_manager.py::_default_mods_root`：

1. 环境变量 `XCAGI_MODS_ROOT` 或 `XCAGI_MODS_DIR`（**首选**，容器化 / 多实例场景必须）。
2. `app` 包同级目录的 `mods/`（默认开发态）。
3. `os.getcwd() + "/mods"`。
4. 从 cwd 向上最多 3 层寻找 `mods/`。

---

## 16. 打包、签名、安装

`app/infrastructure/mods/package.py::ModPackage` 负责打包与校验：

- 产物：`<mod_id>-<version>.mod.zip`
- 压缩内容：整个 Mod 目录（扣除 `__pycache__`、`.DS_Store` 等）
- 目录哈希：`compute_directory_hash(...)` 对路径 + 内容做 sha256 级联，用于签名与完整性校验

### 打包命令（参考）

```bash
# 假定已有 scripts/dev/package_mod.py 或 MODstore CLI，命令形态示意：
python -m app.infrastructure.mods.package pack mods/my-mod --out dist/my-mod-1.0.0.mod.zip
```

### 安装流程

1. 前端 / CLI 接收 `.mod.zip`。
2. `ModPackage.extract_package(zip_path, temp_dir, verify_signature=True)` 校验签名 + 元数据。
3. 解压到 `<mods_root>/<manifest.id>/`（覆盖或拒绝按策略）。
4. 调 `ModManager.load_mod(mod_id)`；失败时 `_record_load_failure` 写入诊断。
5. 路由注册需要**重启主进程**才能生效（FastAPI 路由树非热插拔）；前端提示。

### 签名（企业分发）

当前 `verify_signature=True` 走的是内部 manifest hash 比对 + 可选公私钥签名字段。生产分发链参考 `MODstore/docs/adr/0001-modstore-scope-and-debug-model.md`。

---

## 17. 测试与冒烟

### 17.1 Mod 单测（推荐形态）

利用 FastAPI `TestClient` + SDK monkey-patch 模式；无需起整机：

```python
# tests/mods/test_my_mod_routes.py
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 本 Mod 的 entry；通过 import_mod_backend_py 同样形态载入
from app.mod_sdk.mods_bus import import_mod_backend_py

MOD_PATH = "mods/my-mod"


@pytest.fixture
def client():
    module = import_mod_backend_py(MOD_PATH, "my-mod", "blueprints")
    app = FastAPI()
    module.register_fastapi_routes(app, "my-mod")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_hello(client):
    r = client.get("/api/mod/my-mod/hello")
    assert r.status_code == 200
    assert r.json()["success"] is True
```

对 SDK 层打 patch 时，指向**真模块路径**：

```python
monkeypatch.setattr("app.mod_sdk.services.get_products_service", lambda: fake_svc)
```

（而不是对着自己 `services.py` 顶部重 import 后的名字改；模块级 import 绑定的是函数 globals 的名字查找，你改 mod_sdk 这个源头才会生效。）

### 17.2 聚合冒烟

仓库根提供一键冒烟：

```bash
python scripts/dev/smoke_all.py
```

会依次跑：

1. **Mod 边界 lint**（`scripts/dev/check_mod_import_boundaries.py`）
2. **werkzeug shim parity**（`scripts/dev/smoke_werkzeug_shim.py`，验证密码哈希与 secure_filename 与 werkzeug 行为一致）
3. **FastAPI 整机启动**（`get_fastapi_app()` 路由数 sanity）
4. **参数自由 GET 路由扫描**（`scripts/smoke_paramfree_get_routes.py`，全量跑无参 GET 路由，验证没有 404/405/5xx）

CI 强烈建议把前两步作为 blocking steps。

---

## 18. 从零到上架的工作流

```
┌──────────────────┐
│ 1. scaffold      │  cp -r MODstore/templates/skeleton mods/my-mod
│                  │  sed -i 's/__MOD_ID__/my-mod/g' mods/my-mod/...
│                  │  sed -i 's/__MOD_NAME__/我的 Mod/g' mods/my-mod/...
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. 编辑          │  backend/blueprints.py   ← register_fastapi_routes + mod_init
│                  │  backend/services.py     ← 业务代码，只 import app.mod_sdk.*
│                  │  frontend/routes.js      ← Vue 路由 + 菜单
│                  │  frontend/views/*.vue    ← 页面
│                  │  manifest.json           ← 补 hooks / comms / workflow_employees
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 3. 本地跑        │  python run.py  (XCAGI 主入口)
│                  │  浏览器打开 http://localhost:5000/api/mod/my-mod/hello
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. 边界 / 冒烟    │  python scripts/dev/check_mod_import_boundaries.py
│                  │  python scripts/dev/smoke_all.py
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. 单测          │  pytest tests/mods/test_my_mod_routes.py
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 6. 打包          │  python -m app.infrastructure.mods.package pack mods/my-mod
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 7. 安装 / 分发    │  上传 dist/my-mod-1.0.0.mod.zip 到 MODstore 或 放到目标机
│                  │  解压 → <mods_root>/my-mod/ → 重启主进程
└──────────────────┘
```

---

## 19. 常见反模式


| 反模式                                                    | 正确做法                                              |
| ------------------------------------------------------ | ------------------------------------------------- |
| `from app.services.xxx import yyy`                     | 走 `app.mod_sdk.services`（没有就在 SDK 层加再 re-export）  |
| `from flask import Blueprint`                          | 用 `fastapi.APIRouter` + `register_fastapi_routes` |
| `from werkzeug.utils import secure_filename`           | `app.utils.secure_filename`（主程已用纯 stdlib 替代）      |
| `from werkzeug.security import generate_password_hash` | `app.utils.password_hash`（同上）                     |
| Mod 顶层做 `engine = create_engine(...)`                  | 放到 `mod_init()` 或路由 lazy getter 里                 |
| 在 hook handler 里抛异常中断主程流程                              | `try/except`吞掉并 log；hook 不能反向否决主程业务               |
| comms handler 里阻塞 30s 做大计算                             | 拆成任务队列，comms 只返回 task_id，后续通过 HTTP 轮询             |
| `from app.db.models import *` 拉 ORM 全家桶                | 只从 `app.mod_sdk.db_models` 拿明确需要的模型；长期目标是走高层服务    |
| 两个 Mod 都注册 `comms.register("X", "get")`                | 通道名加 mod 前缀或点分层（`mymod.get.snapshot`）             |
| Mod 根目录里存 runtime 产物（cache、logs）                       | 写数据库或 `tempfile`；Mod 包是只读的                        |
| 在 manifest 里声明 `hooks.shipment.created` 但没写 handler    | 启动日志会告警；要么补 handler，要么删声明                         |
| 路由前缀写成 `/api/<mod_id>` 而不是 `/api/mod/<mod_id>`         | 严格走 `/api/mod/<mod_id>/...`，权限中间件依赖该前缀识别 Mod      |


---

## 20. 参考实现

仓库内现成 Mod，按复杂度升序：


| Mod                 | 路径                      | 展示点                                                                                                                                                                                          |
| ------------------- | ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **example-mod**     | `mods/example-mod/`     | 最小骨架：一条 hello 路由 + 一个 comms 通道（ping）。从这里起步。                                                                                                                                                  |
| **taiyangniao-pro** | `mods/taiyangniao-pro/` | 中等：含考勤文件上传 / 转换、菜单覆盖、workflow_employee 占位。                                                                                                                                                   |
| **sz-qsm-pro**      | `mods/sz-qsm-pro/`      | 完整形态：多路由（dashboard / advanced-settings / batch-process / smart-recommend / qa-packages / phone-agent）、hook、comms、workflow_employee（电话业务员）、同 Mod 内多模块动态加载、私有依赖（`faster-whisper`、`miniaudio`）。 |


**模板脚手架**：`MODstore/templates/skeleton/`（变量：`__MOD_ID`_*、`__MOD_NAME_`*）。

**SDK 源码**：`app/mod_sdk/`；每个子模块都写了用途 docstring，这是权威真相。

**ModManager 源码**：`app/infrastructure/mods/`；`manifest.py` / `mod_manager.py` / `hooks.py` / `comms.py` / `package.py` / `employee_registry.py` 六大文件构成 Mod 引擎。

---

## 附录 A：快速 Checklist

开发一个 Mod 上线前逐项自查：

- `manifest.json` 有 `id` / `name` / `version` / `backend.entry`
- `backend/blueprints.py` 有 `register_fastapi_routes(app, mod_id)`
- 路由前缀严格是 `/api/mod/<mod_id>/...`
- 所有 `from app.`* 走 `app.mod_sdk.`*；`check_mod_import_boundaries.py` 0 violation
- 无 `from flask ...` / `from werkzeug ...`
- `frontend/routes.js` 导出 `<modName>Routes` + `<modName>Menu`
- manifest 里 `hooks` 声明的 handler 在 `backend/<module>.py` 里真的存在
- `comms.exports[]` 声明的通道在 `mod_init()` 里真的 `register()` 了
- workflow_employees 的 `phone_agent_base_path` 对应路由真的实现了 `status/start/stop/statu`
- 没有在模块顶层起线程 / 连 DB / IO
- 带了 `tests/mods/test_<mod_id>_routes.py`
- 本地 `python scripts/dev/smoke_all.py` 4 steps 全绿
- 打包通过：`python -m app.infrastructure.mods.package pack mods/<mod_id>`

---

**文档维护**：SDK 新增符号时同步更新 §6；主程新增 hook 事件时同步更新 §9.1。