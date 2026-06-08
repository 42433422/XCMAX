# Agentic Business OS — 回滚快照

这些 dashboard 真值源文件不在任何 git 仓库内（工作区根非 git，仅 `FHD/` 是仓库），
故此目录提供"改动前原始版"快照 + 一键回滚脚本，保证 Agentic BOS 加固可完整撤销。

## 一键回滚

```bash
bash docs/xcagi-dashboard/_agentic-bos-rollback/ROLLBACK.sh
```

执行后：3 个文件还原到改动前原始版；当前（含改动）版本自动另存为
`_pre-rollback-<时间戳>/`，避免误回滚不可逆。

## 快照内容（`*.orig` = 改动前原始版）

| 文件 | 还原目标 | 说明 |
|---|---|---|
| `emp-wf-radial-graph.js.orig` | `docs/xcagi-dashboard/` | 时间轨（研发发版闭环）原始版 |
| `event-merged-arch-graph.js.orig` | `docs/xcagi-dashboard/` | 事件轨（经营闭环）原始版 |
| `daily_digest_node_employees.json.orig` | `docs/xcagi-dashboard/` | 节点→员工映射原始版 |
| `XCAGI-Full-Pipeline.html.orig` | 工作区根 | 全景页（#s-loops 六线 + #s-workflow Mermaid + cadence 表）原始版 |

## 本轮 Agentic BOS 加固改了什么（回滚即移除以下内容）

时间轨新增：`DRFAIL` 灾备降级、`FASTGATE` 即时推送门禁、`ROLLBACK` 自动回滚、`HEAL` 自愈，
及相应边与跨轨桥接 desc。

事件轨新增：`O4_FAIL` 收费失败、`O8_REJ` 签收驳回、`GOV` 经营治理，及相应边；
`O4`/`O8` 改为 decision 分叉。

映射新增：上述 7 个新节点的主责/协作员工。

HTML 同步（`XCAGI-Full-Pipeline.html`）：`#s-workflow` Mermaid 三段加 DRFAIL/FASTGATE/CANARY/ROLLBACK/HEAL；
`#s-loops` 六线 P5/P6/P7 卡片补对齐说明；cadence 表加「发布门禁 · 回滚/自愈」行。

> 验证：`*.orig` 已通过 `node --check`（JS）/ `JSON.parse`（JSON），且不含任何新节点 token。

## 后端运行时层（FASTGATE + GOV）回滚

`backend/` 子目录单独管理后端改动（FHD git 脏 + sibling 非 git，故用快照）：

```bash
bash docs/xcagi-dashboard/_agentic-bos-rollback/backend/ROLLBACK_BACKEND.sh
```

后端本次改了什么：
- **FASTGATE**（新增 `成都修茈科技有限公司/MODstore_deploy/modstore_server/installer_fastgate.py` + 接入 `digest_daily_line_chain.execute_installer_employee_chain`）：installer/major 快路径推 COS / 回写下载 SSOT 前，强制 staging + /api/health + 市场下载页 smoke 门禁；不过则阻断推送、不写 last_push。开关 `MODSTORE_INSTALLER_FASTGATE_ENABLED`（默认 1）。
- **GOV**（`operations_line_bridge.compute_governance_summary` + 网关/应用服务透出 + `GET /api/operations-line/governance/summary`）：聚合 O4 收费 / O8 签收 / O10 对账 + 断点 → SLA + 风控标记 + 总体状态。
