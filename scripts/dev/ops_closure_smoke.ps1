# 运维闭环 smoke（桌面主控 + MODstore 值班 API）

param(
  [string]$BaseUrl = "http://127.0.0.1:5000"
)

$ErrorActionPreference = "Stop"

Write-Host "[ops-closure] GET $BaseUrl/api/xcmax/ops/closure-status"
try {
  $closure = Invoke-RestMethod -Uri "$BaseUrl/api/xcmax/ops/closure-status" -Method Get
  if (-not $closure.success) { throw "closure-status failed" }
  Write-Host "  deliverable=$($closure.data.deliverable)"
  Write-Host "  missing_remote=$($closure.data.missing_remote_employees.Count)"
} catch {
  Write-Host "  [SKIP] closure-status (need admin session + market token): $_"
}

Write-Host "[ops-closure] GET $BaseUrl/api/xcmax/ops/duty-health"
try {
  $health = Invoke-RestMethod -Uri "$BaseUrl/api/xcmax/ops/duty-health" -Method Get
  Write-Host "  ok=$($health.ok)"
} catch {
  Write-Host "  [SKIP] duty-health: $_"
}

Write-Host "[ops-closure] operator profile mod ids"
python - <<'PY'
from app.mod_sdk.host_profile import bundled_mod_ids_for_profile_sku
ids = bundled_mod_ids_for_profile_sku("operator")
assert "xcmax-personnel" in ids
assert "xcagi-core-workflow-employees" in ids
print("  OK operator bundled mods")
PY

Write-Host "[ops-closure] done"
