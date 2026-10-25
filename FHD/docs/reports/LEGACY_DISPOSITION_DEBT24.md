# Legacy disposition — debt24 (2026-10-25 Asia/Shanghai)

基准 tip：`fd7c00034` 起分支 `debt/24-closeout`。

## 数量

| 指标 | 值 |
|------|-----|
| `FHD/app/legacy` 文件 / py | 61 / 48 |
| 生产引用文件（G4 棘轮） | 54（未恶化） |

## 为何未物理清空

仍被生产路径引用（节选）：

- `app.legacy.chat.legacy_chat_adapter` ← conversation / planner
- `app.legacy.routes.*` ← mounts / workflow / product / templates
- `app.legacy.knowledge.*` ← knowledge_v1
- `app.legacy.market_llm` ← modstore_adapter
- `app.legacy.lan` ← LAN bridge

零引用才能删。本轮不制造假「已删除」。

## 已有迁移证据（前序 + 本轮）

- 前序 #2629：`legacy_vo` → domain VO；conversation 归域；G4 棘轮锁定。
- 本轮：保持棘轮 54；补充本 disposition；禁止新增 `legacy_*.py` 于 `app/legacy` 外（G4.2）。

## 下一刀（非本 PR 部署范围）

1. `document_templates_compat` → application office 服务（已有部分吸收）。
2. `market_llm.openai_compat` → infrastructure LLM 适配。
3. mounts/compat 注册表改为显式 compat 包名（非 legacy 目录）后再删空目录。
