# v10-A hotfix: sync migrate + deliverable-status fix, build enterprise backend (v10 line)
param(
  [string]$FhdRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [switch]$SkipBuild,
  [switch]$DeployOnly
)

$ErrorActionPreference = 'Stop'
Set-Location $FhdRoot

$installBackend = Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\resources\backend'
$distBackend = Join-Path $FhdRoot 'dist\xcagi-backend'

function Write-Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

function Wait-HttpJson {
  param(
    [string]$Uri,
    [int]$TimeoutSec = 180,
    [scriptblock]$Ready
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-RestMethod -Uri $Uri -TimeoutSec 10
      if (& $Ready $resp) { return $resp }
    } catch {
      # backend still starting
    }
    Start-Sleep -Seconds 2
  }
  throw "timeout waiting for $Uri"
}

if (-not $DeployOnly) {
  Write-Step 'build enterprise backend (SkipFrontend)'
  & (Join-Path $FhdRoot 'scripts\package\build-backend.ps1') -Version '1.0.0.1' -SkipFrontend -ProductSku enterprise
  if ($LASTEXITCODE -ne 0) { throw 'build-backend.ps1 failed' }
}

if (-not (Test-Path (Join-Path $distBackend 'xcagi-backend.exe'))) {
  throw "missing dist backend: $distBackend\xcagi-backend.exe"
}

Write-Step 'stop existing xcagi-backend'
Get-Process xcagi-backend -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Step "deploy to $installBackend"
if (-not (Test-Path $installBackend)) { throw "install backend dir missing: $installBackend" }
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
$bak = "$installBackend.bak-$stamp"
Copy-Item $installBackend $bak -Recurse -Force
robocopy $distBackend $installBackend /MIR /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed exit $LASTEXITCODE" }

Write-Step 'restart XCAGI'
Get-Process XCAGI -ErrorAction SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }
Start-Sleep -Seconds 3
Get-Process XCAGI -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\XCAGI.exe')
Start-Sleep -Seconds 5

$base = 'http://127.0.0.1:17500'
Write-Step 'wait for health'
$h = Wait-HttpJson -Uri ($base + '/api/health') -Ready { param($r) $r.status -eq 'healthy' }
Write-Step 'wait for deliverable-status (bootstrap route)'
$d = Wait-HttpJson -Uri ($base + '/api/platform-shell/deliverable-status') -Ready { param($r) $r.success -eq $true }
Write-Host "health=$($h.status) version=$($h.version)"
Write-Host "deliverable=$($d.data.deliverable) mods_routes=$($d.data.mods_routes_loaded) blockers=$($d.data.blockers.Count)"

Write-Step 'OTA migrate-only probe'
$be = Join-Path $installBackend 'xcagi-backend.exe'
$ud = Join-Path $env:APPDATA 'XCAGI'
$env:XCAGI_DESKTOP_MODE = '1'
$env:XCAGI_DATA_DIR = $ud
& $be --desktop --migrate-only --backup --data-dir $ud 2>&1 | ForEach-Object { Write-Host $_ }
Write-Host "migrate exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { throw 'migrate-only failed after hotfix' }

Write-Host '=== v10-A hotfix deploy OK ===' -ForegroundColor Green
