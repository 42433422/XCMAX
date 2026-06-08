# ADR 0003：artifact 类型、组合包（bundle）与独立 AI 员工包（employee_pack）

- **状态**：已采纳  
- **日期**：2026-04-18  

## 背景

MOD 与「AI 员工」、组合上架（一袋多物）混用同一 zip 与 `manifest.json` 时，运行时校验、商店索引与安装路径难以扩展；公网目录需区分产物类型。

## 决策

1. **顶层字段 `artifact`**（缺省视为 `mod`，与旧包 100% 兼容）：
   - `mod`：现有 XCAGI 扩展（backend/frontend 可选但沿用原校验规则）。
   - `employee_pack`：独立 AI 员工包；根级 `employee` 对象字段与 `workflow_employees[]` 单项对齐；**首期挂载策略**为 `scope: "global"`（安装到 `mods/_employees/<pack_id>/`），**预留** `host_mod`（二期）。
   - `bundle`：组合袋；通过 `bundle.contains`（远程/本地索引 ref）与/或 `bundle.embeds`（包内相对路径子 zip）声明成员；**嵌套深度上限** 2，避免依赖炸弹。

2. **物理扩展名**：`.xcmod`（mod 或兼容）、`.xcemp`（employee_pack，便于 CDN 与统计）；内容均为 zip，沿用 `META-INF/signature.json` 约定（与 mod 包一致）。

3. **扫描约定**：`mods_root` 下**顶层**以 `_` 开头的目录名为保留名（如 `_employees/`），`ModManager.scan_mods` 不将其当作 mod 目录扫描。

4. **付费与授权**：不在本 ADR 实现；公网 `PackageRecord` 预留 `commerce`、`license` 字段（见 catalog API）。

## 后果

- MODstore 与 XCAGI 的 manifest 校验需双端同步演进（先警告后收紧）。
- 前端需将 `type === "employee_pack"` 排除在「当前扩展 Mod」单选之外，但仍参与 `workflow_employees` 合并。
