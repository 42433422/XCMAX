# Neuro Bus 边界（项 23）

## 生产入口（稳定）

- `app.neuro_bus.bus` / `get_neuro_bus` — 主总线
- `app.neuro_bus.command_gateway` — 命令入口
- `app.neuro_bus.initializer` — 进程内初始化
- `app.neuro_bus.dead_letter_queue` — 死信

## 实验 / 兼容

- `deprecated_sliding_window.py` — 已废弃，仅测试与 `rate_limiter` 兼容导出；新代码用 TokenBucket
- `domains/`、`integrations/` — 域桥与集成，按需加载

## 不做

- 不为「撑叙事」增加空模块
- 不在本轮删除仍被测试引用的 deprecated 适配

编排叙事以**稳定入口 + 契约测试**为准，不以文件数为准。

## debt19 orchestration surface

- agent_registry / agent_dispatcher
- orchestration_saga
- capability_router
