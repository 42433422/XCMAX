$ErrorActionPreference = 'Continue'
$EV = "C:\Users\97088\Desktop\xcmax-release-ssot-staging\evidence\e2e\windows-release-1.0.0.2\t9\chain\post-reboot"
$INSTALL = "$env:LOCALAPPDATA\Programs\XCAGI"
function Log($m) { $stamp = (Get-Date).ToString('HH:mm:ss'); Write-Output "[$stamp] $m" }

Log "post-reboot verification starting (boot at $((Get-CimInstance Win32_OperatingSystem).LastBootUpTime))"

# 1. wait 30s for logon settle
Start-Sleep -Seconds 30

# 2. launch app if not running
$running = Get-Process -Name XCAGI -ErrorAction SilentlyContinue
if (-not $running) {
  Log "launching XCAGI cold after system reboot"
  Start-Process -FilePath (Join-Path $INSTALL 'XCAGI.exe') -WorkingDirectory $INSTALL
} else {
  Log "XCAGI already running (auto-launch enabled)"
}

# 3. wait health up to 240s
$health = $null
$deadline = (Get-Date).AddSeconds(240)
while ((Get-Date) -lt $deadline) {
  try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:17500/api/health' -TimeoutSec 5 -NoProxy
    break
  } catch { Start-Sleep -Seconds 5 }
}
Log ("health: " + $(if ($health) { ($health | ConvertTo-Json -Compress -Depth 3) } else { 'NOT-REACHABLE in 240s' }))
$health | ConvertTo-Json -Depth 5 | Set-Content -Path (Join-Path $EV 'post-reboot-health.json') -Encoding UTF8

# 4. build-info
Copy-Item (Join-Path $INSTALL 'resources\build-info.json') (Join-Path $EV 'post-reboot-buildinfo.json') -Force
$bi = Get-Content (Join-Path $EV 'post-reboot-buildinfo.json') -Raw | ConvertFrom-Json
Log ("build-info: version=" + $bi.version + " gitSha=" + $bi.gitSha)

# 5. process inventory
$procs = Get-Process -Name XCAGI, xcagi-backend -ErrorAction SilentlyContinue | Select-Object Name, Id
Log ("processes: " + (($procs | ForEach-Object { "$($_.Name)#$($_.Id)" }) -join ' | '))
$procs | ConvertTo-Json | Set-Content (Join-Path $EV 'post-reboot-processes.json')

# 6. db counts (copy then read)
Start-Sleep -Seconds 3
$data = "$env:APPDATA\XCAGI\data"
foreach ($n in @('xcagi.db', 'xcagi.db-wal', 'xcagi.db-shm')) {
  $src = Join-Path $data $n
  if (Test-Path $src) { Copy-Item $src (Join-Path $EV $n) -Force }
}
try {
  $con = New-Object System.Data.SQLite.SQLiteConnection
  $ok = $false
} catch { }
# use python for sqlite read (PS lacks built-in sqlite)
$py = @"
import json, sqlite3, sys
con = sqlite3.connect(r'$EV\xcagi.db')
cur = con.cursor()
out = {}
for t in ('sessions','users','products'):
    out[t] = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
out['last_products'] = [r[0] for r in cur.execute('SELECT name FROM products ORDER BY id DESC LIMIT 5')]
print(json.dumps(out))
"@
$tmp = Join-Path $EV 'read-db.py'
Set-Content -Path $tmp -Value $py -Encoding UTF8
$cnt = & python $tmp 2>&1
Log ("db counts: $cnt")
Set-Content -Path (Join-Path $EV 'post-reboot-dbcounts.json') -Value ($cnt -join "`n") -Encoding UTF8

# 7. desktop screenshot
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Start-Sleep -Seconds 10
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
$bmp.Save((Join-Path $EV 'post-reboot-desktop.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Log "screenshot saved"

# 8. business probe via health + products API needs session; record summary instead
$summary = [ordered]@{
  boot_time     = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')
  verify_time   = (Get-Date).ToString('o')
  app_version   = $bi.version
  app_sha       = $bi.gitSha
  health_status = if ($health) { $health.status } else { 'unreachable' }
  db_counts     = $cnt
}
$summary | ConvertTo-Json | Set-Content (Join-Path $EV 'post-reboot-summary.json') -Encoding UTF8
Set-Content (Join-Path $EV 'DONE.marker') -Value (Get-Date).ToString('o')
Log "post-reboot verification DONE"
