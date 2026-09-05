$ErrorActionPreference = 'Stop'
$verifier = Join-Path $PSScriptRoot 'verify-windows-signature.ps1'
$fixture = New-TemporaryFile
$previousTestStatus = $env:XCAGI_SIGNATURE_POLICY_TEST_STATUS
function Get-AuthenticodeSignature {
  param([string]$LiteralPath)
  [PSCustomObject]@{
    Status = $env:XCAGI_SIGNATURE_POLICY_TEST_STATUS
    StatusMessage = 'policy test fixture'
    SignerCertificate = [PSCustomObject]@{Subject = 'CN=Expected Publisher'; Thumbprint = 'fixture'}
    TimeStamperCertificate = [PSCustomObject]@{Subject = 'CN=Timestamp'}
  }
}
function Assert-Policy {
  param([string]$Status, [bool]$Allow, [bool]$ShouldPass, [string]$Publisher = 'Expected Publisher')
  $env:XCAGI_SIGNATURE_POLICY_TEST_STATUS = $Status
  $passed = $false
  try {
    & $verifier -Path $fixture.FullName -ExpectedPublisher $Publisher -AllowUnsigned:$Allow
    $passed = $true
  } catch {
    if ($ShouldPass) { throw }
  }
  if ($passed -ne $ShouldPass) { throw "Wrong policy result: Status=$Status Allow=$Allow" }
}
try {
  Assert-Policy NotSigned $false $false
  Assert-Policy NotSigned $true $true
  foreach ($status in @('HashMismatch', 'NotTrusted', 'UnknownError', 'NotSupportedFileFormat', 'Incompatible')) {
    Assert-Policy $status $true $false
  }
  Assert-Policy Valid $false $true
  Assert-Policy Valid $true $true
  Assert-Policy Valid $true $false 'Wrong Publisher'
  Write-Host 'PASS: signature policy (10 cases); unsigned is not invalid-signed.'
} finally {
  $env:XCAGI_SIGNATURE_POLICY_TEST_STATUS = $previousTestStatus
  Remove-Item -LiteralPath $fixture.FullName -Force
}
