param(
  [Parameter(Mandatory = $true)]
  [string]$Path,

  [string]$ExpectedPublisher = '',
  [switch]$AllowUnsigned
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Path)) {
  throw "Installer or executable not found: $Path"
}

if (-not $ExpectedPublisher) {
  $ExpectedPublisher = $env:XCAGI_WINDOWS_PUBLISHER_NAME
}
if (-not $ExpectedPublisher) {
  $ExpectedPublisher = '成都修茈科技有限公司'
}

$signature = Get-AuthenticodeSignature -LiteralPath $Path
Write-Host "Authenticode path: $Path"
Write-Host "Authenticode status: $($signature.Status)"
Write-Host "Authenticode message: $($signature.StatusMessage)"

if ($AllowUnsigned -and $signature.Status -eq 'NotSigned') {
  Write-Warning 'UNSIGNED: manual installer delivery only; not eligible for stable automatic updates.'
  return
}
if ($signature.Status -ne 'Valid') {
  throw "Invalid Authenticode signature: $($signature.Status) $($signature.StatusMessage)"
}
if (-not $signature.SignerCertificate) {
  throw 'Authenticode status is Valid but the signer certificate is missing.'
}

$subject = $signature.SignerCertificate.Subject
if ($ExpectedPublisher -and $subject -notlike "*$ExpectedPublisher*") {
  throw "Unexpected Authenticode signer subject: $subject"
}
if (-not $signature.TimeStamperCertificate) {
  throw 'Authenticode signature is valid but has no trusted timestamp certificate.'
}

Write-Host 'OK: Authenticode Status=Valid'
Write-Host "Signer: $subject"
Write-Host "Signer thumbprint: $($signature.SignerCertificate.Thumbprint)"
Write-Host "Timestamp signer: $($signature.TimeStamperCertificate.Subject)"
