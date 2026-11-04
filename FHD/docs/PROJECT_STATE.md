# 项目真实状态（SSOT）

## 客服闭环总线

客服工单由 MODstore `incident_bus` 与 `incident_team` 驱动；边界与事件契约见 [`CUSTOMER_TICKET_BUS_SSOT.md`](./architecture/CUSTOMER_TICKET_BUS_SSOT.md)。

能力、交付、覆盖率及外部对标的当前证据见生成视图 [`PRODUCT_LINES_STATUS.md`](PRODUCT_LINES_STATUS.md) 与 [`AUDIT_BENCHMARK_SSOT.md`](AUDIT_BENCHMARK_SSOT.md)；本文不复制分级、测试数量或阶段矩阵。

## PR #2631 架构治理的边界

本次整理模块位置、兼容入口、端口、扩展目录及版本入口，不等于 19 项架构债务全部消除。结构指标由 `scripts/ci/check_structure_gates.py` 从当前源码计算，不维护第二份手写测量快照。

- 原清单 1–5、9–11、14、16、18–21：结构调整及兼容入口已实现；目录、文件数量和命名收敛不能替代语义分层与端侧验收。
- 原清单 6–7：增加安全模块和总线组件，不据此宣称权限统一或业务恢复闭环。
- 原清单 12–13：仍有三个超过 100 KiB 的第一方非测试 Python 模块，当前 G12 基线为 3，并非清零。
- 原清单 15：LangGraph `pregel/main.py` 保留上游实现，结构门禁按第三方依赖排除，并未完成该文件拆分。
- `scripts/dev/layer_ratchet_baseline.json` 中仍有迁移过渡反向依赖白名单；后续应通过显式端口逐步替换，不能把移动目录视为消除依赖。

失效的 `DEBT19_CLOSEOUT.md`、`DEBT19_MEASUREMENT.json` 已合并到本节；原件及 SHA256 留存仓库外归档 `~/XCMAX-runtime/artifact-archive/pr2631-20261025/receipt.json`。发布、真实 macOS 运行及 76 项 Harness 验收另行验证，不由本 PR 的结构门禁代替。

## 仍未解决（别假装）

2026-10-21 九项审计追踪（仅登记未闭环事项，不代表交付或关单；保留历史 1.0.0.6 验收，不改写生产及客户数据）：

| ID | 问题 | 状态与剩余证据 |
|---|---|---|
| 01 | 收款幂等与等额分期 | Open：[集成候选 #2459](https://github.com/42433422/XCMAX/pull/2459) 保留 #2449；真实 PostgreSQL 17 项收款断言、完整备份升级链及三库原所有者/权限恢复已验证；发布前新备份、主线发布与真实交付仍待完成。 |
| 02 | 离线桥接账号隔离 | Open：#2449 的离线桥接 14 项回归在 Node 24 全部通过且无跳过；实际安装软件的账号切换、登出及归属验收仍待完成。 |
| 03 | Agent 工具截止时间 | Open：[集成候选 #2459](https://github.com/42433422/XCMAX/pull/2459) 保留 #2451；90507c 旧冻结候选的60秒默认工具隔离与回收证据保留，不能冒充当前产物。16e5c2f 组合的20项真实流程与344项RAG回归通过，新增标量回传、认证租户恢复与持久后台消费；记忆跨进程事务与私有原子写入已通过工程回归；当前CI、精确主线构建发布及客户验收仍待完成。 |
| 04 | 调度恢复与 SLO | Open：#2453 曾读回健康，后续再次出现 self_maintenance_remediation_loop 失败；持续恢复、每日任务记录及生产 SHA 绑定的 SLO/积压验收尚未完成。 |
| 05 | MODstore 间歇线程异常 | Open：需复现、定位并重复并发验证，单次重跑成功不能销项。 |
| 06 | 覆盖率证据 | Open：当前覆盖率报告与验收提交 SHA 的对应关系仍需核实，不沿用旧报告。 |
| 07 | 工单完整生命周期 | Open：#2459 仍为 draft，未合入 main；17 单仍处理中，部署、真实验收、回写和生产积压验收均未完成。 |
| 08 | 编号 Mixin 与动态导入 | Open：显式依赖和恢复类型检查的完整证据待补。 |
| 09 | JWT 刷新跨进程状态 | Open：#2449 已有真实 PostgreSQL 多进程单次消费与新进程拒重放证据（SSH 验证等待放宽至90秒，不作为原20秒性能通过）；旧 refresh 需重登，上线须排空旧刷新进程，不得混部或回滚旧实现；实际交付仍待验收。 |

存量生产库若曾跳过 Alembic，部署时须先 stamp/upgrade 对齐；Windows 交付状态与处置见专项 [`WINDOWS_RELEASE_SSOT.md`](WINDOWS_RELEASE_SSOT.md)。
