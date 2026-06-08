# Repository orchestration data

YAML instances validated against JSON Schemas under [`docs/contracts/orchestration/`](../docs/contracts/orchestration/README.md):

| File | Schema |
|------|--------|
| [`deploy_topology.yaml`](deploy_topology.yaml) | `deploy_topology.schema.json` |
| [`ci_pipeline.yaml`](ci_pipeline.yaml) | `ci_pipeline.schema.json` |

Validate locally from `MODstore_deploy/`:

```bash
python scripts/validate_orchestration_yaml.py
```

Why this is separate from **`depends_on`**: employee packs declare **collaboration** for AI duty-graph runs; this folder declares **components and CI/CD** only. See [`docs/orchestration-boundaries.md`](../docs/orchestration-boundaries.md).
