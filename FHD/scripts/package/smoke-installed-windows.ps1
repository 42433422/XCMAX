param(
  [string]$BaseUrl = 'http://127.0.0.1:5000',
  [string]$ProductSku = 'enterprise',
  [string]$InstalledExe = '',
  [switch]$RestartApp,
  [int]$ReadyTimeoutSeconds = 180,
  [string[]]$RequiredModIds = @(
    'xcagi-erp-domain-bridge',
    'xcagi-approval-bridge',
    'xcagi-customer-service-bridge',
    'xcagi-model-payment-bridge',
    'xcagi-lan-license-bridge',
    'xcagi-neuro-bus-bridge',
    'xcagi-office-employee-pack-bridge',
    'xcagi-planner-bridge',
    'xcagi-workflow-visualization-bridge'
  )
)

$ErrorActionPreference = 'Stop'

function Get-DefaultInstalledExe {
  if (-not $env:LOCALAPPDATA) {
    throw 'LOCALAPPDATA is not set; pass -InstalledExe explicitly'
  }
  return (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI\XCAGI.exe')
}

function Invoke-XcagiJson {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [ValidateSet('GET', 'POST')]
    [string]$Method = 'GET',
    [object]$Body = $null,
    [int]$TimeoutSec = 15
  )

  $uri = $BaseUrl.TrimEnd('/') + $Path
  if ($Method -eq 'POST') {
    $jsonBody = if ($null -eq $Body) { '{}' } else { $Body | ConvertTo-Json -Depth 16 }
    $resp = Invoke-WebRequest -Uri $uri -Method Post -Body $jsonBody -ContentType 'application/json' -UseBasicParsing -TimeoutSec $TimeoutSec
  } else {
    $resp = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec $TimeoutSec
  }
  if ($resp.StatusCode -lt 200 -or $resp.StatusCode -ge 300) {
    throw "$Path returned HTTP $($resp.StatusCode)"
  }
  return ($resp.Content | ConvertFrom-Json)
}

function Get-EnvelopeData {
  param([object]$Payload)
  if ($Payload -and ($Payload.PSObject.Properties.Name -contains 'data')) {
    return $Payload.data
  }
  return $Payload
}

function Wait-XcagiReady {
  $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/api/health') -UseBasicParsing -TimeoutSec 2
      if ($resp.StatusCode -eq 200) { return }
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "Backend did not become ready: $BaseUrl/api/health"
}

function Invoke-Check {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [scriptblock]$Body
  )
  try {
    $detail = & $Body
    $script:PassCount += 1
    Write-Host "PASS $Name $detail"
  } catch {
    $script:FailCount += 1
    Write-Host "FAIL $Name $($_.Exception.Message)"
  }
}

if ($RestartApp) {
  if (-not $InstalledExe) {
    $InstalledExe = Get-DefaultInstalledExe
  }
  if (-not (Test-Path $InstalledExe)) {
    throw "Installed exe not found: $InstalledExe"
  }
  Get-Process XCAGI,xcagi-backend -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-Process -FilePath $InstalledExe | Out-Null
}

Wait-XcagiReady

$script:PassCount = 0
$script:FailCount = 0

Invoke-Check 'health' {
  $resp = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + '/api/health') -UseBasicParsing -TimeoutSec 5
  "code=$($resp.StatusCode)"
}

Invoke-Check 'desktop-status' {
  $status = Invoke-XcagiJson '/api/desktop/status'
  if (-not $status.readyForUi) { throw 'readyForUi false' }
  if (-not $status.modsReady) { throw 'modsReady false' }
  "readyForUi=$($status.readyForUi);modsReady=$($status.modsReady);storageMode=$($status.storageMode)"
}

Invoke-Check 'runtime-product-sku' {
  $payload = Invoke-XcagiJson '/api/runtime/product-sku'
  $data = Get-EnvelopeData $payload
  if ($data.sku -ne $ProductSku) {
    throw "sku=$($data.sku), expected=$ProductSku"
  }
  "sku=$($data.sku);enterprise=$($data.is_enterprise_edition)"
}

Invoke-Check 'mods-list' {
  $payload = Invoke-XcagiJson '/api/mods'
  $mods = @(Get-EnvelopeData $payload)
  $ids = @($mods | ForEach-Object { $_.id })
  foreach ($modId in $RequiredModIds) {
    if (-not ($ids -contains $modId)) {
      throw "missing $modId"
    }
  }
  "count=$($ids.Count)"
}

Invoke-Check 'mods-loading-status' {
  $payload = Invoke-XcagiJson '/api/mods/loading-status'
  $data = Get-EnvelopeData $payload
  if ($data.load_mismatch) { throw 'load_mismatch true' }
  if ($data.partial_failure) { throw 'partial_failure true' }
  "loaded=$($data.mods_loaded);partial_failure=$($data.partial_failure)"
}

foreach ($modId in $RequiredModIds) {
  Invoke-Check "mod-detail:$modId" {
    $payload = Invoke-XcagiJson "/api/mods/$modId"
    $data = Get-EnvelopeData $payload
    if ($data.id -ne $modId) { throw "id=$($data.id)" }
    'code=200'
  }
}

Invoke-Check 'purchase-summary' {
  Invoke-XcagiJson '/api/purchase/summary' | Out-Null
  'code=200'
}

Invoke-Check 'report-dashboard' {
  Invoke-XcagiJson '/api/report/dashboard' | Out-Null
  'code=200'
}

Invoke-Check 'mobile-pairing-issue' {
  $payload = Invoke-XcagiJson '/api/mobile/v1/pairing/issue' -Method POST -Body @{
    deviceName = 'PackageSmoke'
    platform = 'windows-smoke'
  } -TimeoutSec 10
  $data = Get-EnvelopeData $payload
  $code = @($data.shortCode, $data.code, $data.pairingCode | Where-Object { $_ } | Select-Object -First 1)
  if (-not $code -or -not $code[0]) { throw 'missing pairing code' }
  "code=200;pairingCode=$($code[0])"
}

Invoke-Check 'erp-mod-products-list' {
  Invoke-XcagiJson '/api/mod/xcagi-erp-domain-bridge/products/list?page=1&per_page=1' | Out-Null
  'code=200'
}

Invoke-Check 'erp-mod-purchase-units' {
  Invoke-XcagiJson '/api/mod/xcagi-erp-domain-bridge/purchase_units' | Out-Null
  'code=200'
}

Invoke-Check 'compat-products-list' {
  Invoke-XcagiJson '/api/products/list?page=1&per_page=1' | Out-Null
  'code=200'
}

Invoke-Check 'compat-purchase-units' {
  Invoke-XcagiJson '/api/purchase_units' | Out-Null
  'code=200'
}

Write-Host "SMOKE_PASS=$script:PassCount"
Write-Host "SMOKE_FAIL=$script:FailCount"

if ($script:FailCount -ne 0) {
  throw "Installed Windows smoke failed: $script:FailCount"
}

