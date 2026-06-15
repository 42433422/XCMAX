param(
  [string]$Version = "10.0.0",
  [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Version = $Version.TrimStart("v", "V")

# 仓根 = FHD 的上级（XCMAX）
$FhdRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$RepoRoot = Resolve-Path (Join-Path $FhdRoot "..")
$DeliveryDir = Join-Path $RepoRoot "太阳鸟"
$Data424 = Join-Path $DeliveryDir "数据\424"
$Sku = "enterprise"
$SetupName = "XCAGI-Enterprise-Setup-$Version-x64.exe"
$ReleaseExe = Join-Path $FhdRoot "release\xcagi-v$Version\$Sku\$SetupName"

New-Item -ItemType Directory -Force -Path $DeliveryDir | Out-Null
New-Item -ItemType Directory -Force -Path $Data424 | Out-Null

if (-not $SkipBuild) {
  Write-Host "==> Building Enterprise Windows installer (v$Version) ..."
  & (Join-Path $PSScriptRoot "build-installer.ps1") -Version $Version -ProductSku enterprise
} else {
  Write-Host "==> SkipBuild: using existing release artifact if present."
}

if (-not (Test-Path $ReleaseExe)) {
  throw "Installer not found: $ReleaseExe`nRun without -SkipBuild on a Windows dev machine, or copy the exe to that path first."
}

$destExe = Join-Path $DeliveryDir $SetupName
Copy-Item $ReleaseExe $destExe -Force
Write-Host "Copied: $destExe"

# 可选：考勤模板（FHD/424 在 .gitignore，仅本地有则打入交付包）
$src424 = Join-Path $FhdRoot "424"
$tplName = "考勤-2026-3月份考勤统计表.xlsx"
$tplSrc = Join-Path $src424 $tplName
if (Test-Path $tplSrc) {
  Copy-Item $tplSrc (Join-Path $Data424 $tplName) -Force
  Write-Host "Copied template: $tplName"
  Get-ChildItem $src424 -Filter "*.xlsx" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne $tplName } |
    ForEach-Object {
      Copy-Item $_.FullName (Join-Path $Data424 $_.Name) -Force
      Write-Host "Copied extra xlsx: $($_.Name)"
    }
} else {
  Write-Warning "Template not found at $tplSrc — delivery will be installer-only. Place template under 太阳鸟\数据\424\ manually before handoff."
}

# manifest.json
$hash = (Get-FileHash $destExe -Algorithm SHA256).Hash.ToLower()
$manifest = @{
  product       = "太阳鸟 PRO"
  delivery_id   = "customer-taiyangniao"
  version       = $Version
  sku           = $Sku
  installer     = $SetupName
  sha256        = $hash
  built_at      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  mod_ids       = @("attendance-industry", "taiyangniao-pro")
  template_path = "数据/424/$tplName"
  notes         = "Windows enterprise installer; Mod via xiu-ci.com account entitlement"
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $DeliveryDir "manifest.json") -Encoding UTF8

Write-Host ""
Write-Host "Done. Delivery folder:"
Write-Host "  $DeliveryDir"
Write-Host "  - $SetupName ($([math]::Round((Get-Item $destExe).Length / 1MB, 1)) MB)"
Write-Host "  - manifest.json"
if (Test-Path (Join-Path $Data424 $tplName)) {
  Write-Host "  - 数据\424\$tplName"
}
