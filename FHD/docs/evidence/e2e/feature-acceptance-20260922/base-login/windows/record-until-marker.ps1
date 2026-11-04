# record-until-marker.ps1 - record the desktop with ffmpeg until a marker file appears.
# Stops ffmpeg through its stdin ("q") so the mp4 gets its index written (a killed ffmpeg would
# leave an unplayable file). Used for the operator phases whose length is not known in advance.
param(
    [Parameter(Mandatory = $true)][string]$OutFile,
    [Parameter(Mandatory = $true)][string]$StopMarker,
    [int]$MaxSeconds = 600,
    [string]$Ffmpeg = 'C:\xcagi-test\ffmpeg\ffmpeg.exe'
)
$ErrorActionPreference = 'Continue'
if (-not (Test-Path $Ffmpeg)) { $Ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source }
if (-not $Ffmpeg) { Write-Host 'ffmpeg not found'; exit 2 }
$args = @('-hide_banner', '-loglevel', 'error', '-f', 'gdigrab', '-framerate', '5', '-i', 'desktop',
          '-c:v', 'h264_mf', '-b:v', '600k', '-pix_fmt', 'yuv420p', '-y', $OutFile)
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Ffmpeg
$psi.Arguments = ($args -join ' ')
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.CreateNoWindow = $true
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()
Write-Host ('recording -> ' + $OutFile)
$end = (Get-Date).AddSeconds($MaxSeconds)
while ((Get-Date) -lt $end -and -not (Test-Path $StopMarker)) { Start-Sleep -Seconds 2 }
try { $proc.StandardInput.WriteLine('q'); $proc.WaitForExit(20000) | Out-Null } catch { }
if (-not $proc.HasExited) { try { $proc.Kill() } catch { } }
if (Test-Path $OutFile) { Write-Host ('saved ' + (Get-Item $OutFile).Length + ' bytes') }