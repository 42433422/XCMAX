# MODstore_deploy（姊妹栈 · 全仓实体）

日更全链路、Vibe 双清单、`daily_action_items` 行动看板、派发/部署状态回写的 **Python 后端实体**落在此目录。

## 关键模块

| 模块 | 职责 |
|------|------|
| `modstore_server/digest_vibe_prep.py` | Vibe 预备 → 更新/补丁双清单 MD |
| `modstore_server/digest_action_items.py` | 解析 MD → `daily_action_items` 落库 + 回写 |
| `modstore_server/action_items_api.py` | `GET /api/admin/action-items` 等 API |
| `modstore_server/daily_digest.py` | 08:00 digest 主流程（含 action items 钩子） |
| `modstore_server/digest_line_executor.py` | 派发成功 → `dispatched` 回写 |
| `modstore_server/approval_dispatcher.py` | 部署合并 → `merged` 回写 |

## 本地启动

```bash
bash FHD/scripts/dev/run_modstore_daily_local.sh restart
```

默认使用本目录（工作区 `成都修茈科技有限公司/MODstore_deploy`）；若目录缺失则回退 `~/XCMAX-archives/.../MODstore_deploy`。

## 前端看板

`XCAGI-Full-Pipeline.html` → `#s-gaps` / `#s-roadmap` 由 `docs/xcagi-dashboard/emp-wf-action-items.js` 拉取本栈 `:8788` API 动态渲染。
