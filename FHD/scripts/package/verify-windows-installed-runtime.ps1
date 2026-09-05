param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,

  [string]$ExpectedPublisher = '',
  [switch]$AllowUnsigned,

  [Parameter(Mandatory = $true)]
  [string]$ExpectedBuildSha,

  [Parameter(Mandatory = $true)]
  [string]$ExpectedProductVersion,

  [int]$ReadyTimeoutSeconds = 240,

  [string]$InstallDir = ''
)

$ErrorActionPreference = 'Stop'

$signatureVerifier = Join-Path $PSScriptRoot 'verify-windows-signature.ps1'
$runtimeSmoke = Join-Path $PSScriptRoot 'smoke-installed-windows.ps1'

function Stop-XcagiProcesses {
  Get-Process -Name 'XCAGI', 'xcagi-backend' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

function Wait-PathRemoved {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [int]$TimeoutSeconds = 60
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-Path -LiteralPath $Path)) {
      return
    }
    Start-Sleep -Seconds 1
  }
  throw "Timed out waiting for uninstall to remove: $Path"
}

if (-not (Test-Path -LiteralPath $InstallerPath)) {
  throw "Windows installer not found: $InstallerPath"
}
if (-not $AllowUnsigned -and -not $ExpectedPublisher.Trim()) {
  throw 'ExpectedPublisher is required; use the exact organization text from the issued certificate Subject.'
}
if ($ExpectedBuildSha -notmatch '^[0-9a-fA-F]{40}$') {
  throw "ExpectedBuildSha must be the full 40-character Git SHA, got '$ExpectedBuildSha'."
}
if ($ExpectedProductVersion -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') {
  throw "ExpectedProductVersion must be x.y.z or x.y.z.w, got '$ExpectedProductVersion'."
}
if (-not (Test-Path -LiteralPath $signatureVerifier)) {
  throw "Windows signature verifier missing: $signatureVerifier"
}
if (-not (Test-Path -LiteralPath $runtimeSmoke)) {
  throw "Installed runtime smoke script missing: $runtimeSmoke"
}
if (-not $env:RUNNER_TEMP -and -not $InstallDir) {
  throw 'RUNNER_TEMP is not set; pass InstallDir explicitly.'
}
if (-not $env:APPDATA) {
  throw 'APPDATA is not set; cannot verify uninstall data-retention policy.'
}

$InstallerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
$ExpectedPublisher = $ExpectedPublisher.Trim()
$ExpectedBuildSha = $ExpectedBuildSha.Trim().ToLowerInvariant()
$ExpectedProductVersion = $ExpectedProductVersion.TrimStart('v', 'V')

if (-not $InstallDir) {
  $identity = @(
    $env:GITHUB_RUN_ID,
    $env:GITHUB_RUN_ATTEMPT,
    [Guid]::NewGuid().ToString('N').Substring(0, 8)
  ) | Where-Object { $_ }
  $InstallDir = Join-Path $env:RUNNER_TEMP ("xcagi-installed-runtime-" + ($identity -join '-'))
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)

$installedExe = Join-Path $InstallDir 'XCAGI.exe'
$backendExe = Join-Path $InstallDir 'resources\backend\xcagi-backend.exe'
$buildInfoPath = Join-Path $InstallDir 'resources\build-info.json'
$skuPath = Join-Path $InstallDir 'resources\product-sku.json'
$uninstaller = Join-Path $InstallDir 'Uninstall XCAGI.exe'
$dataRoot = Join-Path $env:APPDATA 'XCAGI'
$markerName = "ci-uninstall-retention-$([Guid]::NewGuid().ToString('N')).txt"
$retentionMarker = Join-Path $dataRoot $markerName
$installed = $false
$uninstalled = $false

try {
  Write-Host "Verifying installer before installation (AllowUnsigned=$AllowUnsigned): $InstallerPath"
  & $signatureVerifier -Path $InstallerPath -ExpectedPublisher $ExpectedPublisher -AllowUnsigned:$AllowUnsigned

  Stop-XcagiProcesses
  Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $InstallDir) | Out-Null

  Write-Host "Installing package silently into: $InstallDir"
  $installProcess = Start-Process `
    -FilePath $InstallerPath `
    -ArgumentList @('/S', "/D=$InstallDir") `
    -Wait `
    -PassThru
  if ($installProcess.ExitCode -ne 0) {
    throw "NSIS silent installation failed with exit code $($installProcess.ExitCode)."
  }
  $installed = $true

  foreach ($requiredPath in @(
    $installedExe,
    $backendExe,
    $buildInfoPath,
    $skuPath,
    $uninstaller
  )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
      throw "Installed package is missing required path: $requiredPath"
    }
  }

  $buildInfo = Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json
  $actualBuildSha = ([string]$buildInfo.gitSha).Trim().ToLowerInvariant()
  $actualVersion = ([string]$buildInfo.version).TrimStart('v', 'V')
  if ($actualBuildSha -ne $ExpectedBuildSha) {
    throw "Installed build-info Git SHA mismatch: actual=$actualBuildSha expected=$ExpectedBuildSha"
  }
  if ($actualVersion -ne $ExpectedProductVersion) {
    throw "Installed build-info version mismatch: actual=$actualVersion expected=$ExpectedProductVersion"
  }

  $skuInfo = Get-Content -LiteralPath $skuPath -Raw | ConvertFrom-Json
  if ([string]$skuInfo.sku -ne 'enterprise') {
    throw "Installed product SKU mismatch: actual=$($skuInfo.sku) expected=enterprise"
  }

  Write-Host 'Verifying installed executable signatures.'
  & $signatureVerifier -Path $installedExe -ExpectedPublisher $ExpectedPublisher -AllowUnsigned:$AllowUnsigned
  & $signatureVerifier -Path $backendExe -ExpectedPublisher $ExpectedPublisher -AllowUnsigned:$AllowUnsigned

  Stop-XcagiProcesses
  Write-Host "Launching installed desktop runtime: $installedExe"
  $appProcess = Start-Process `
    -FilePath $installedExe `
    -WorkingDirectory $InstallDir `
    -PassThru
  Start-Sleep -Seconds 3
  $appProcess.Refresh()
  if ($appProcess.HasExited) {
    throw "Installed XCAGI process exited before runtime smoke (exit=$($appProcess.ExitCode))."
  }

  & $runtimeSmoke `
    -InstalledExe $installedExe `
    -ReadyTimeoutSeconds $ReadyTimeoutSeconds `
    -ProductSku enterprise

  $appProcess.Refresh()
  if ($appProcess.HasExited) {
    throw "Installed XCAGI process exited during runtime smoke (exit=$($appProcess.ExitCode))."
  }

  New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
  Set-Content `
    -LiteralPath $retentionMarker `
    -Value "XCAGI uninstall retention check $ExpectedBuildSha" `
    -Encoding UTF8

  Stop-XcagiProcesses
  Write-Host "Uninstalling package silently: $uninstaller"
  $uninstallProcess = Start-Process `
    -FilePath $uninstaller `
    -ArgumentList @('/S') `
    -Wait `
    -PassThru
  if ($uninstallProcess.ExitCode -ne 0) {
    throw "NSIS silent uninstall failed with exit code $($uninstallProcess.ExitCode)."
  }
  Wait-PathRemoved -Path $installedExe
  $uninstalled = $true

  if (-not (Test-Path -LiteralPath $retentionMarker)) {
    throw 'Uninstall unexpectedly deleted XCAGI user data; deleteAppDataOnUninstall must remain false.'
  }

  Write-Host "OK: installer installed, launched, passed runtime smoke, and uninstalled (AllowUnsigned=$AllowUnsigned)."
  Write-Host "OK: installed buildSha=$actualBuildSha version=$actualVersion sku=$($skuInfo.sku)"
  Write-Host "OK: uninstall retained user data marker=$retentionMarker"
} finally {
  Stop-XcagiProcesses

  if ($installed -and -not $uninstalled -and (Test-Path -LiteralPath $uninstaller)) {
    try {
      $cleanupUninstall = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList @('/S') `
        -Wait `
        -PassThru
      Write-Host "Cleanup uninstall exit=$($cleanupUninstall.ExitCode)"
    } catch {
      Write-Warning "Cleanup uninstall failed: $($_.Exception.Message)"
    }
  }

  Remove-Item -LiteralPath $retentionMarker -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}
