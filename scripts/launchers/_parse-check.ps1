$errs = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'start-lan.ps1'),
    [ref]$null,
    [ref]$errs
)
if ($errs.Count) {
    $errs | ForEach-Object { '{0}: {1}' -f $_.Extent.StartLineNumber, $_.Message }
} else {
    'Parse OK'
}
