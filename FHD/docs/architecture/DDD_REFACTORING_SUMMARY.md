# DDD 架构重构阶段总结

最后更新：2026-07-13

## 当前结论

DDD 方向已经落到可执行的依赖守卫，但全仓重构尚未完成。当前状态应描述为：

- HTTP 路由已不再直接依赖 `app.services`，实测与基线均为 0。
- AI 对话与 workflow 两个关键宿主已从“厚服务/强宿主”改为显式组合的薄门面。
- `app/services` 仍有 126 个 Python 文件；全仓仍有 90 个已登记巨型文件。
- 因此不能再使用“DDD 重构完成”作为全仓结论，后续工作是继续消减既有基线。

## 本轮已完成

| 项目 | 重构前 | 当前 |
|---|---:|---:|
| `ai_chat_app_service.py` | 约 1800 行、Mixin 聚合 | 386 行、显式组合 |
| `application/tools/workflow.py` | 1635 行 | 175 行 |
| 路由直连 `app.services` | 6 个基线文件，另有新违规 | 0 |
| `chat_business_safety.py` | 1207 行 | 450 行 |
| `services/ocr_service.py` | 572 行 | 446 行，backend 迁入 infrastructure |
| `arch_fitness` 基线 | 含重复、已修复和路由豁免 | 93 个当前真实债项 |

AI 对话拆分后的主要职责边界：

- `application/ai_chat_app_service.py`：稳定用例入口与依赖装配。
- `application/ai_chat/`：动态 workflow、Excel 导入、响应、即时工具、trace 等协作者。
- `application/tools/workflow.py`：兼容门面与 registry cache。
- `application/tools/workflow_*`：注册、调度、Excel 分析和导入用例。

路由通过合同、发票、微信、用户记忆和 MODstore chat 等 application facade 调用既有实现，
不再绕过应用层。

## 永久守卫

1. `scripts/dev/check_layer_ratchet.py`
   - `app/services/**/*.py` 文件数不得高于 126。
   - `fastapi_routes` 直连 `app.services` 基线为 0。
2. `scripts/arch_fitness.py`
   - `app/` 新增超过 500 行的文件立即失败。
   - 两个关键宿主必须存在、不得超过 500 行、不得继承 `*Mixin`。
   - 既有债只允许从 `arch_fitness_baseline.txt` 删除，不允许新增豁免。

## 仍未完成

- 90 个既有巨型文件仍需按域逐批拆分，其中优先级最高的是 agent orchestrator、
  group chat、移动 API 扩展和剩余厚 application service。
- 3 个 domain→infrastructure 依赖仍需改为 port/interface。
- `services/` 中的领域规则、基础设施和用例编排仍需继续归位；本轮只冻结了新增。

这份文档记录当前架构阶段状态。历史“已完成”描述仅代表早期 Auth 样板，不再代表全仓状态。
