param(
  [Parameter(Mandatory = $true)]
  [string]$PayloadPath
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PayloadPath)) {
  throw "NSIS payload missing: $PayloadPath"
}

$sevenZip = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'electron-builder\Cache') -Recurse -Filter '7za.exe' -ErrorAction SilentlyContinue |
  Select-Object -First 1
if (-not $sevenZip) {
  throw "7za.exe was not found under electron-builder cache; cannot verify the NSIS payload filter"
}

$listing = & $sevenZip.FullName l -slt $PayloadPath
if ($LASTEXITCODE -ne 0) {
  throw "7za could not list $PayloadPath (exit $LASTEXITCODE)"
}

$methods = @($listing | Where-Object { $_ -like 'Method = *' } | ForEach-Object { $_.Substring(9).Trim() } | Where-Object { $_ })
$blocked = @($methods | Where-Object { $_ -match 'BCJ2|ARM64|Delta' })
if ($blocked.Count -gt 0) {
  throw "NSIS payload contains a 7z filter Nsis7z cannot decode: $($blocked | Select-Object -Unique -First 8 -Join '; ')"
}
$hasBcj = @($methods | Where-Object { $_ -match '(^| )BCJ( |$)' }).Count -gt 0
if (-not $hasBcj) {
  throw "NSIS payload has no BCJ-filtered executable entries; the installer filter pin did not take effect"
}

Write-Host "NSIS payload filter OK: BCJ present, BCJ2/ARM64 absent ($($methods.Count) method rows)"
exit 0
