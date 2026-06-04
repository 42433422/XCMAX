# FHD Helm charts

## xcagi

Main backend chart templating [`k8s/`](../k8s/) manifests.

```bash
# Render locally (compare with raw YAML)
helm template xcagi ./charts/xcagi -f charts/xcagi/values-staging.yaml \
  --set image.repository=ghcr.io/org/repo/backend \
  --set image.tag=sha-dev

# Install / upgrade
helm upgrade --install xcagi ./charts/xcagi \
  -n default \
  -f charts/xcagi/values-production.yaml \
  --set image.repository=ghcr.io/org/repo/backend \
  --set image.tag=sha-abc \
  --wait
```

CI deploy: [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) uses `helm upgrade` when kubeconfig is configured.

**Frontend**: images are built in CI but not deployed by this chart (CDN / separate ingress). See chart `values.yaml` comments.

**Secrets**: create `xcagi-secrets` out-of-band (`k8s/secret.yaml.example`). Do not commit real secrets.

**Canary / blue-green**: raw overlays remain in `k8s/canary.yaml` and `k8s/blue-green-deployment.yaml`; enable via chart values in a follow-up.

**Deprecated**: `XCAGI/k8s/` duplicate tree — use `charts/xcagi` + `k8s/` only.
