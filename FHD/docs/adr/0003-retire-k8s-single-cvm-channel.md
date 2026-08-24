# ADR-0003 退役 K8s/Helm/蓝绿/金丝雀部署，收敛为 CVM tarball+compose 单通道

- 状态：已采纳（2026-07-14 决策；2026-08-01 物理删除 `FHD/k8s/`、`FHD/helm/`）
- 决策者：DevOps / 工程负责人
- 涉及文件：
  - `docs/CI_SSOT.md`（部署章节）
  - `.github/workflows/fhd-deploy.yml`（break-glass 通道）
  - `FHD/scripts/deploy/`（tarball / compose 脚本）

## 背景

项目曾维护一套 Kubernetes + Helm 部署体系，并设计了 blue-green / canary / GitOps
多策略。但实际情况是：

1. **从未接通真实集群**——所有 K8s/Helm 清单长期处于「无人部署、无人验证」状态，
   属于纯负债资产；
2. **真实生产只有一台腾讯云 CVM**（`119.27.178.147`），跑 tarball + docker compose；
3. 维护两套（其中一套是假的）部署描述，造成文档与现实的持续漂移，误导新贡献者
   与 AI 智能体。

## 决策

1. **退役所有未接通的部署策略**：blue-green / canary / GitOps / 预览环境清单与
   文档路径全部删除；`kubectl` / `KUBE_CONFIG` 相关配置停用。
2. **物理删除**：2026-08-01 真删除 `FHD/k8s/`（含 `k8s/monitoring/` 的 k6 yaml）
   与 `FHD/helm/`。
3. **唯一生产通道**：单台 CVM，tarball 模式为默认（`fhd-pack-release.sh` →
   `fhd-push-release.sh` → cron 自动应用），compose 镜像模式为 Phase 2 备选。
4. **`fhd-deploy.yml` 降级为 break-glass**：仅 SSH 到 CVM 执行 `apply-latest` 或
   `restart-only`，不承担常规发布。
5. **回滚**：`fhd-apply-release.sh` 健康检查失败自动回滚备份目录；错误制品用
   `.hold` 重命名冻结，防止 cron 反复重试。

## 后果

- **正面**：部署描述与现实 1:1 对应，文档不再撒谎；维护面大幅缩小；发布路径单一、
  可被 cron 全自动驱动。
- **代价**：放弃多副本/滚动扩容能力（当前单实例足够）；未来若需横向扩展需重新
  引入编排层（届时应基于真实需求重建，而非复活死代码）。
- **教训**：部署策略的价值取决于「是否真实运行」，未接通的清单是负资产。

## 关联

- `docs/CI_SSOT.md` 部署章节（含 2026-07-14 退役记录）
- 健康检查：`https://xiu-ci.com/fhd-api/api/health`
