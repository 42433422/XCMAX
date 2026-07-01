param(
  [Parameter(Mandatory = $true)]
  [string]$Path,

  [string]$ExpectedPublisher = "成都修茈科技有限公司"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path)) {
  throw "Installer not found: $Path"
}

$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne "Valid") {
  throw "Invalid Authenticode signature: $($signature.Status) $($signature.StatusMessage)"
}

$subject = $signature.SignerCertificate.Subject
if ($ExpectedPublisher -and $subject -notlike "*$ExpectedPublisher*") {
  throw "Unexpected signer subject: $subject"
}

Write-Host "OK: Authenticode signature is valid"
Write-Host "Signer: $subject"
Write-Host "Thumbprint: $($signature.SignerCertificate.Thumbprint)"
