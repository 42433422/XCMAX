param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('personal', 'enterprise')]
  [string]$ProductSku
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$modsRoot = Join-Path $Root "mods"
$stageDir = Join-Path $Root "build\staged-mods-$ProductSku"

$readProfileScript = Join-Path $PSScriptRoot "read-host-profile-stage-ids.py"
$idsJson = (& python $readProfileScript $ProductSku) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "read-host-profile-stage-ids.py failed" }
$parsedIds = $idsJson | ConvertFrom-Json
$ids = @()
foreach ($id in $parsedIds) {
  $ids += [string]$id
}

$excludeAlways = @('taiyangniao-pro', 'sz-qsm-pro', '_employees', 'industry-solutions')

if (Test-Path $stageDir) {
  Remove-Item $stageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

foreach ($modId in $ids) {
  if ($excludeAlways -contains $modId) { continue }
  $src = Join-Path $modsRoot $modId
  if (-not (Test-Path $src)) {
    throw "Required profile mod not found: $modId ($src)"
  }
  $dst = Join-Path $stageDir $modId
  Copy-Item -Path $src -Destination $dst -Recurse -Force
  Write-Host "Staged: $modId"
}

# `_employees` remains excluded as a marketplace tree. The built-in Office
# docking bridge is part of the host UI, so bundle only the employee packs in
# its catalog; otherwise a clean install exposes controls with no executor.
$officeCatalog = Join-Path $modsRoot "xcagi-office-employee-pack-bridge\config\office_pack_catalog.json"
$employeeSourceRoot = Join-Path $modsRoot "_employees"
$employeeStageRoot = Join-Path $stageDir "_employees"
if (-not (Test-Path $officeCatalog)) {
  throw "Missing Office employee catalog: $officeCatalog"
}
New-Item -ItemType Directory -Force -Path $employeeStageRoot | Out-Null
$officePackIds = (Get-Content -Raw -Encoding UTF8 $officeCatalog | ConvertFrom-Json).pack_ids
foreach ($packIdRaw in $officePackIds) {
  $packId = [string]$packIdRaw
  if ([string]::IsNullOrWhiteSpace($packId)) { continue }
  $src = Join-Path $employeeSourceRoot $packId
  if (-not (Test-Path $src)) {
    throw "Missing required Office employee pack: $packId"
  }
  $dst = Join-Path $employeeStageRoot $packId
  Copy-Item -Path $src -Destination $dst -Recurse -Force
  Write-Host "Staged Office employee: $packId"
}

Write-Host "Staged $($ids.Count) mod(s) for SKU $ProductSku -> $stageDir"
