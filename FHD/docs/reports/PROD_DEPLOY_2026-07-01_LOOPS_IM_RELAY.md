# 生产部署配方：loops 真干活 + 员工主动 IM 到手机 + 超级员工闭环（2026-07-01）

本次部署对应分支 `claude/elegant-keller-d730cf`（整合 charming-wescoff 热补回灌 + PR#101 + 任务完成推送）。
目标：AI 员工 loop 真执行 → 干完主动发 IM 到老板手机（公网可达）→ 超级员工手机派工
→ 桌面 CLI 执行 → 终态推送手机。

> 已核实 main 里早就有：平台身份路由（`platform_llm_scope` + `_self_maintenance_actor_user_id`
> 默认 uid=0）、配额失败熔断、`scheduler_job_runs` 账本 + `/api/scheduler/runtime`、
> 孤儿 running 任务 poll 时自动重入队（`XCAGI_RELAY_RUNNING_TTL_SEC` 默认 900s）。
> **PR#92 已被取代，可以关闭。**

## 0. 前置

- 本分支的 PR 已合入 main。
- 生产机 119.27.178.147；FHD 在 `/opt/fhd-full`（端口 5100，env `/root/fhd-full.env`），
  MODstore 运行代码在 `/root/XCMAX`。
- ⚠️ 部署必须全量同步 app 树，严禁单文件热补（历史上单文件部署搞挂过现网）。

## 1. 备份

```bash
ssh root@119.27.178.147
cp -a /opt/fhd-full /opt/fhd-full.bak.$(date +%m%d%H%M)
cp -a /root/XCMAX/成都修茈科技有限公司/MODstore_deploy/modstore_server \
      /root/modstore_server.bak.$(date +%m%d%H%M)
```

## 2. 同步代码

```bash
# /root/XCMAX 若是本仓库 checkout（用 git status 确认）：
cd /root/XCMAX && git fetch origin && git checkout main && git pull --ff-only

# /opt/fhd-full 全量同步 FHD 后端（app 树 + alembic）：
rsync -a --delete /root/XCMAX/FHD/app/ /opt/fhd-full/app/
rsync -a /root/XCMAX/FHD/alembic/ /opt/fhd-full/alembic/
```

（`mobile_notification_outbox` 表由 `enqueue_outbox` 运行时 `checkfirst` 自建，
生产 `FHD_SKIP_ALEMBIC=1` 不影响。）

## 3. 配置 env（首次需要）

先生成一把共享内部密钥：`openssl rand -hex 32`，两侧填同一个值。

`/root/fhd-full.env` 追加（FHD 侧）：

```
XCAGI_MARKET_INTERNAL_API_KEY=<KEY>          # internal_im/employee-im 鉴权 + CSRF 豁免
XCAGI_MODSTORE_INTERNAL_URL=http://127.0.0.1:<MODstore端口>   # 老板回复→回流员工问答
```

MODstore 侧 env（`/root/XCMAX/.env` 或 systemd unit 的 EnvironmentFile，与现有键同处）追加：

```
FHD_INTERNAL_EMPLOYEE_IM_URL=http://127.0.0.1:5100/api/internal/employee-im/send
XCAGI_MARKET_INTERNAL_API_KEY=<同一把KEY>
FHD_BOSS_USER_ID=<老板的 users.id>            # psql 查: SELECT id,username FROM users ORDER BY id LIMIT 5;
XCAGI_FHD_INTERNAL_URL=http://127.0.0.1:5100
```

说明：
- `employee_im_bridge`（员工干完→IM 汇报）三件套缺一即静默禁用（best-effort 不报错），
  所以这步是"员工会说话"的开关。
- MODstore 端口用 `ss -ltnp | grep -iE 'uvicorn|python'` 确认后填上面的 `<MODstore端口>`。
- 平台 LLM（loops 身份 uid=0 用）：已配 mimo 且 PONG；如需显式指定
  `MODSTORE_EMPLOYEE_BENCH_PROVIDER` / `MODSTORE_EMPLOYEE_BENCH_MODEL`。

## 4. 起服务

```bash
systemctl restart fhd-full
systemctl restart modstore            # web(单元名以 systemctl list-units 为准)
systemctl enable --now modstore-scheduler   # loops 调度器,2026-06-22 曾停摆 12 天
```

## 5. 验收清单（一条条打勾）

```bash
# ① 调度器活着 + job 不 stale（在生产机上, 端口按实际）
curl -s http://127.0.0.1:<MODstore端口>/api/scheduler/runtime | head -c 600

# ② 公网 IM 端点不再 lan_blocked（本地任何网络, 用手机登录后的 Bearer）
curl -s https://xiu-ci.com/fhd-api/api/im/conversations -H "Authorization: Bearer <token>"
# 预期 200+JSON; 若 403 lan_blocked 说明 /opt/fhd-full 没同步到位

# ③ 员工 IM 内部通道（生产机上）
curl -s -X POST http://127.0.0.1:5100/api/internal/employee-im/send \
  -H "X-Internal-Api-Key: <KEY>" -H "Content-Type: application/json" \
  -d '{"boss_user_id":<uid>,"employee_id":"e2e-probe","display_name":"链路探针","body":"部署验收:看到这条说明员工→手机通了"}'
# 手机应弹通知(渠道 xcagi_chat)或轮询后出现

# ④ 离线推送队列
curl -s "https://xiu-ci.com/fhd-api/api/mobile/v1/notifications/pending" -H "Authorization: Bearer <token>"

# ⑤ 超级员工端到端: 手机→超级开发部发一个任务 → Mac 桌面端(需在跑)领取执行
#    → 干完手机收到「✅ 超级员工任务完成」推送(本次新增)
```

## 6. 回滚

```bash
systemctl stop fhd-full && rm -rf /opt/fhd-full && mv /opt/fhd-full.bak.<时间戳> /opt/fhd-full && systemctl start fhd-full
cd /root/XCMAX && git checkout <上一个提交> && systemctl restart modstore modstore-scheduler
```

## 尚未闭环（后续）

- 员工 loop 的 shell_exec/高危动作仍走 Para 桥或审批门（安全设计，不是 bug）；
  要"无人值守跑重活"需配 `MODSTORE_PARA_API_BASE` 或保持 Mac 端 Para/桌面中继在线。
- 超级员工 tier-1 依赖 Mac 桌面端进程在线（`mobile_relay_desktop_client` 轮询 4s）。
- FCM 未配则推送全走离线队列轮询（App 后台 ~15 分钟一拉），配
  `FIREBASE_SERVICE_ACCOUNT_JSON` 可秒达（国内机型仍以轮询为主）。
