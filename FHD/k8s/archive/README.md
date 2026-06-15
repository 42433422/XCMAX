# Archived K8s manifests

| File | Superseded by |
|------|----------------|
| `canary.yaml` | Argo Rollouts canary (`FHD/k8s/rollouts/rollout.yaml` + `analysis-template.yaml`) |
| `blue-green-deployment.yaml` | Argo Rollouts (`FHD/gitops/apps/rollouts.yaml`) |

`fhd-deploy.yml` break-glass path always applies a **rolling** `Deployment`; progressive delivery is GitOps-only.
