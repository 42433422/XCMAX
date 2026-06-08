# ADR 0001：MODstore 边界与「切换 Mod 调试」模型

- **状态**：已采纳  
- **日期**：2026-04-04  

## 背景

XCAGI 在进程启动时扫描 `mods_root` 下全部带 `manifest.json` 的目录并加载；`manifest.primary` 仅影响排序，不能实现「运行时只启用某一个 Mod」而不改 XCAGI 核心。

## 决策

1. **MODstore** 作为独立子项目，负责本地 **library** 中的 Mod 管理、校验、zip 导入导出、与 `XCAGI/mods` 的文件级同步（push/pull）。
2. **隔离调试** 通过生成仅含单个 Mod 的目录树，将环境变量 **`XCAGI_MODS_ROOT`** 指向该目录，并 **重启 XCAGI 后端** 完成；不在首版实现进程内热切换 Mod。

## 后果

- **优点**：与现有 XCAGI `ModManager` 行为一致，无需改动 Flask 蓝图生命周期，风险可控。  
- **缺点**：调试切换依赖重启；开发者需在文档中明确该流程（见主 README 与 `/debug` 页）。
