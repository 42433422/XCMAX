# ADR-0002 后端采用 DDD 四层架构 + 仓储实现唯一性约束

- 状态：已采纳（追溯记录，决策发生于 2026-06 前后）
- 决策者：架构负责人
- 涉及目录：
  - `app/domain/`（限界上下文 + `ports/` 端口接口）
  - `app/application/`（应用服务 / 用例编排）
  - `app/infrastructure/repositories/`（仓储实现，唯一真相源）
  - `app/fastapi_routes/`（HTTP 适配层）
  - `scripts/dev/repository_ssot.py`（AST 扫描强制约束）

## 背景

FHD 后端早期按功能模块平铺，随业务域（customer / employee / shipment / product /
persona / neuro 等）扩张，出现三类结构性问题：

1. **领域逻辑泄漏**：业务规则散落在路由与 ORM 查询里，跨模块复用靠复制；
2. **仓储多实现**：同一 `<Entity>Repository` 端口在不同目录（含遗留 `persistence/`）
   出现多份实现，行为漂移、难以判断哪份是权威；
3. **依赖方向混乱**：上层直接依赖具体框架/ORM，替换与测试成本高。

## 决策

采用 **DDD 四层架构**，并用工具链把约束固化成可执行的门禁：

1. **分层与依赖方向**：`domain`（纯领域模型 + `ports/` 端口接口，不依赖框架）→
   `application`（用例编排，依赖 domain 端口）→ `infrastructure`（仓储/外部适配实现）
   → `fastapi_routes`（HTTP 入口）。依赖只能向内，domain 不反向依赖任何外层。
2. **仓储实现唯一性（SSOT）**：每个 `<Entity>Repository` 端口**有且仅有一个实现**，
   且实现必须放在规范目录 `app/infrastructure/repositories/`。
   - 禁止在遗留 `persistence/` 目录新增仓储实现；
   - `persona/` 目录下的专属异步架构实现可豁免唯一性检查（有界例外）。
3. **强制手段**：`repository_ssot.py` 通过 AST 扫描全仓，检测重复实现与目录违规，
   接入 `ssot_cli.py gate` 与 CI `ssot-drift-gate`，违规即阻断。
4. **登记**：`repository-ssot` 域注册进 `config/ssot.yaml` 并在 `SSOT_INDEX.md` 文档化。

## 后果

- **正面**：领域逻辑集中、可测（domain 层无框架依赖）；仓储行为单一权威，杜绝
  「改了 A 实现忘了 B 实现」的漂移；依赖方向可被静态校验。
- **代价**：新增一个聚合需同时落 port + impl + 注册，样板代码多；对不熟悉 DDD 的
  贡献者有学习成本。
- **边界**：`persona/` 异步架构为有界豁免，未来若收敛应回归统一仓储模型。

## 关联

- `repository_ssot.py`、`ssot_cli.py gate`、`config/ssot.yaml`、`SSOT_INDEX.md`
- 见工作区规则「Hard Constraints：同一 Repository port 不允许多实现」。
