# health-sampler.ps1 - poll /api/health and append a JSONL timeline (read-only, no side effects).
param(
    [int]$Seconds = 120,
    [string]$OutFile = 'C:\xcagi-test\tmp\probe\health-timeline.jsonl'
)
$ErrorActionPreference = 'Continue'
try { Add-Type -AssemblyName System.Net.Http -ErrorAction Stop } catch { }
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.UseCookies = $false
$handler.Proxy = $null
$handler.UseProxy = $false
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds(10)
$end = (Get-Date).AddSeconds($Seconds)
$count = 0
while ((Get-Date) -lt $end) {
    $count++
    $line = [ordered]@{ t = (Get-Date).ToString('HH:mm:ss.fff'); http = 0; status = ''; runtime_status = ''; degraded = @(); blockers = @(); failures = @(); err = '' }
    try {
        $resp = $client.GetAsync('http://127.0.0.1:17500/api/health').Result
        $line.http = [int]$resp.StatusCode
        $text = $resp.Content.ReadAsStringAsync().Result
        $j = $text | ConvertFrom-Json
        $line.status = [string]$j.status
        $line.runtime_status = [string]$j.runtime.status
        if ($j.degradedReasons) { $line.degraded = @($j.degradedReasons) }
        if ($j.runtime.blockers) { $line.blockers = @($j.runtime.blockers | ForEach-Object { $_.component }) }
        if ($j.runtime.failures) { $line.failures = @($j.runtime.failures | ForEach-Object { $_.component }) }
    } catch {
        $line.status = 'unreachable'
        $line.err = [string]$_.Exception.Message
    }
    Add-Content -Path $OutFile -Value ($line | ConvertTo-Json -Compress) -Encoding UTF8
    Start-Sleep -Milliseconds 2000
}
$client.Dispose()
Write-Output ("samples=" + $count)