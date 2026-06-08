# Orchestration contracts

JSON Schemas for **deployment topology** and **CI/CD pipeline documentation** live here. They are intentionally separate from employee-pack **`depends_on`** / **`employee_config_v2.collaboration.depends_on`**, which describe AI collaboration only.

| Schema | Purpose |
|--------|---------|
| [`deploy_topology.schema.json`](deploy_topology.schema.json) | Logical components on hosts / rollout edges (DAG). |
| [`ci_pipeline.schema.json`](ci_pipeline.schema.json) | Workflow names, roles, and trigger chains aligned with `.github/workflows/`. |

Authoritative instance files for this repository: [`MODstore_deploy/orchestration/`](../../../orchestration/README.md).

Semantic boundaries: [`orchestration-boundaries.md`](../../orchestration-boundaries.md).
