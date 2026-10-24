# Legacy 退役看板（阶段二解耦 / 阶段三删除）

- 刷新：2026-10-24 Asia/Shanghai
- 原则：先解耦后删除；生产引用 `rg=0` 或豁免到期且无挂载依赖才删
- 基线：33 `.py` / 生产引用文件 ≤56（棘轮只降不升；列车 B/D 后约 53）

## 状态摘要

| 包 | 状态 | 说明 |
|----|------|------|
| `legacy/chat` | 解耦中（#2614） | 主路径经 `application/conversation`；adapter 暂留 infra |
| `legacy/domain` | 解耦中（#2616） | 生产改 `domain.shipment.value_objects`；compat/legacy_vo 仍保留 |
| `legacy/routes/*` mounts | 挂载链仍依赖 | 豁免至阶段三 |
| `legacy/documents` / `workflow` / `lan` | 待 P2/P3 | 未删 |

## 删除门禁

1. `python3 FHD/scripts/ci/check_structure_gates.py --repo .` 中 G4.1 不恶化  
2. 目标模块生产侧 `app.legacy.<mod>` 引用为 0  
3. 无 `legacy_compat` / mounts 动态挂载串  
4. 相关黄金测试绿  

未满足则写入豁免（expires + owner），禁止裸删。
