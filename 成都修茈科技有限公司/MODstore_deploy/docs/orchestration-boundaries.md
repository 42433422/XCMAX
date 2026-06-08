# 协作依赖 vs 部署 / 流水线编排

MODstore 同时存在两套「图」语义，**不可混用**。

## 1. 协作层（AI 员工）

| 来源 | 含义 |
|------|------|
| `manifest.depends_on` | 员工包顶层协作声明 |
| `employee_config_v2.collaboration.depends_on` | V2 协作配置 |

**用途**：描述多名虚拟员工在任务上的协作顺序、上下文承接；驱动管理员 **Duty Graph 运行**（[`admin_duty_graph_api.create_duty_graph_run`](../modstore_server/admin_duty_graph_api.py)），对员工执行器做拓扑排序与执行。

**不是**：服务器拓扑、网络链路、Kubernetes Pod 依赖，也不是 GitHub Actions `needs:` 或 CI/CD DAG。

## 2. 基建层（仓库内单独建模）

| 来源 | 含义 |
|------|------|
| [`orchestration/deploy_topology.yaml`](../orchestration/deploy_topology.yaml) | 逻辑组件（如 backend / market / payment-java）与可选 rollout 边 |
| [`orchestration/ci_pipeline.yaml`](../orchestration/ci_pipeline.yaml) | 与 `.github/workflows/` 对齐的 CI / deploy 工作流与触发链 |

**用途**：文档化并校验真实上线路径；契约见 [`contracts/orchestration/`](contracts/orchestration/README.md)。

**不是**：AI 协作图；不参与 Duty Graph API 的依赖解析。

## 3. 可选指针（员工包 → 基建）

Manifest 可选字段 **`release_hints`** / **`references`**（仅指针，**不包含拓扑边**）：

- `release_hints.component_id` — 对应 `deploy_topology.yaml` 中的 `components[].id`
- `references.ci_workflow` — 对应某个 GitHub Actions workflow 的显示名

Duty Graph **仅**读取协作字段；上述指针仅供运维/文档对照，不参与 `_extract_manifest_dependencies`。

## 4. 小结

- **协作 depends_on**：只管「谁先执行哪位 AI 员工」。
- **orchestration YAML**：只管「组件与 CI/CD」。
- 两者之间 **没有自动桥接**；若需要一致性，由流程与代码评审维护。
