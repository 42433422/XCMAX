param(
  [Parameter(Mandatory = $true)]
  [string]$FilePath,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $FilePath)) {
  throw "Artifact not found: $FilePath"
}

$thumb = $env:WIN_SIGN_CERT_THUMBPRINT
if (-not $thumb) {
  Write-Host "[sign] WIN_SIGN_CERT_THUMBPRINT unset; skipping Authenticode for $FilePath"
  exit 0
}

Write-Host "[sign] Authenticode: $FilePath"
signtool sign /sha1 $thumb /fd SHA256 /tr $TimestampUrl /td SHA256 /a $FilePath
signtool verify /pa $FilePath
Write-Host "[sign] OK"
