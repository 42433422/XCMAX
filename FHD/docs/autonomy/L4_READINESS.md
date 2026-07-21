# 通往 L4：管理端对齐说明

管理端入口：编制工作台 → 自进化 Loop 面板顶部 **L4 Readiness**。

清单代码 SSOT：`FHD/frontend/src/constants/autonomyL4Readiness.ts`  
运行时叠加：`GET …/ops/self-maintenance/status` → `l4_closure.auto_dispatch_deploy`。

## P0-1 诊断摘要（2026-07-21）

- `XCAGI_LLM_API_KEY` / `BASE_URL` / `MODEL` secrets **已配置**
- AI Self-Heal **会触发**（非完全 0%）；大量 `skipped` 是父 workflow 成功时的预期行为
- 失败常见原因：日志无法抽取错误 → 只建 Incident Issue 并 exit 2
- 原监听面偏窄；已扩到 Employee Smoke Gate / MODstore tests 等（内联 workflows 列表，避免 publisher 加 `FHD/` 前缀）

## Staging 路径

`cvm-autonomy-watcher` 矩阵：`/opt/fhd-staging`（optional）+ `/opt/fhd-full`（required）。

独立健康检查（不依赖 prod `/fhd-api`）：

```bash
bash FHD/scripts/deploy/check-staging-health.sh          # 公网 path
bash FHD/scripts/deploy/check-staging-health.sh --ssh    # + CVM 本机 :5101
```

## P1 闭环补齐（2026-07-21）

| 缺口 | 落地 |
|------|------|
| 显式 callback | `FHD/scripts/autonomy/autonomy_callback.py`（`autonomy_callback` / `report_callback` / `deploy_callback`）；deploy 失败 freeze 经 callback 通知 ingest |
| runtime↔source | `MODstore_deploy/scripts/sync-runtime-to-source.sh` + `install-sync-runtime-to-source-cron.sh` |
| 连接点 4 | ledger `implement-pack` → `gh workflow run fhd-ai-issue-implement.yml`；orchestrator 开 issue 时不再打 `ai-implement` 标签 |
