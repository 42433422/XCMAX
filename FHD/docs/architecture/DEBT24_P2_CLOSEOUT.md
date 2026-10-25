# Debt24 P2 closeout notes

2026-10-25 Asia/Shanghai

## domain/ports 旧 3 文件

`FHD/app/domain/ports/` 保留 `cache_port.py` / `embedder.py` + README，作跨上下文共享端口；
新端口落在 `domain/<ctx>/ports.py`（G5.3 要求 ≥7）。去留：共享端口保留，禁止再往旧包堆业务端口。

## NeuroBus / security 边界

- `FHD/app/neuro_bus/BOUNDARY.md`（#2629）
- `FHD/app/security/SSOT.md`（#2629）
本轮不灌空文件；能力以任务生命周期与 CI 安全扫描为准。

## 同名副本

- G8：app 树 noisy basename = 0（棘轮）。
- mods 员工包同名有意保留（契约）。
- `parser/mapper/rules` 完全相同副本：员工包生成物，检测在 G8 排除 mods/XCAGI。

## 多入口 / SKU

见 `DEPLOY_PATH_SSOT.md` + `FHD/VERSION.md` 各端交付等级。
可执行入口清单：`docs/ENTRYPOINTS_SKU.md`（本轮新增）。

## LangGraph vendored

见 `docs/LANGGRAPH_VENDORED.md`（本轮新增）：上游、升级、校验钩子。

## kellai 子模块

见 `docs/KELLAI_SUBMODULE.md`（本轮新增）。

## 变异测试范围

见 `docs/MUTATION_TESTING_SCOPE.md`（本轮新增）：限定 DI/Contexts 等，**不得**宣称为全仓 95%。
