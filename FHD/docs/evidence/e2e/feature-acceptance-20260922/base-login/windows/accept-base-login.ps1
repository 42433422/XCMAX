# accept-base-login.ps1 - Windows real-machine acceptance for feature "base-login" (登录与会话管理).
# THIS ROUND ONLY. No product changes. ASCII-only source (PowerShell 5.1 safe).
#
# Purpose: produce round-fresh, Windows-only evidence for the capability-center feature
#   base-login "登录与会话管理" (catalog: 成都修茈科技有限公司/data/capabilities/catalog.json).
#
# Case set (must match the macOS round, but run independently on Windows):
#   W1 未登录拒绝          GET /api/auth/me + /api/auth/session/validate without session cookie -> valid=false
#   W2 企业账号登录        GUI login with a real enterprise account -> workspace; API session -> /api/auth/me success, account_kind=enterprise
#   W3 会话保持(进程重启)  restart the app process; the same session cookie stays valid (server-side session)
#   W4 安全退出            POST /api/auth/logout -> old cookie rejected; GUI returns to login page
#   W5 边界负例            错误密码拒绝 / 桌面端拒绝 admin 会话 / 空凭据拒绝
#   W6 Web 端同账户体系     the same account also logs in on the market (Web) endpoint
#
# Six-element evidence contract (see windows-evidence-1.0.0.5/rules.json):
#   screenshot + video + log + product_version + app_sha + verify_time -> PASS
#   missing any element -> PARTIAL (never upgrade the verdict by hand)
#
# Usage (run on the Windows real machine, app installed and backend on 127.0.0.1:17500):
#   powershell -ExecutionPolicy Bypass -File .\accept-base-login.ps1 -WithVideo
# Optional:
#   -AppExe "C:\Users\<user>\AppData\Local\Programs\XCAGI\XCAGI.exe"
#   -InstallerPath "C:\...\XCAGI-Enterprise-Setup-1.0.0.5-x64-unsigned.exe"
#   -OutDir "C:\XCAGI-acceptance\feature-base-login"
#
# GUI steps (typing account/password, clicking 登录, clicking 退出登录) are performed by the operator
# (Windows-side agent UI automation) while this script's video/screenshot capture is running.
# Evidence files the operator must place into <OutDir>\shot\ :
#   W2-login-page.png        (login form visible, before typing)
#   W2-login-workspace.png   (after login: workspace with the account name)
#   W4-login-page-again.png  (after logout: back to the login form)

param(
    [string]$Base = 'http://127.0.0.1:17500',
    [string]$Account = 'SUNBIRD',
    [string]$Password = 'SUN123456',
    [string]$MarketBase = 'https://xiu-ci.com',
    [string]$OutDir = (Join-Path $env:TEMP 'win-evidence\feature-base-login'),
    [string]$AppExe = '',
    [string]$InstallerPath = '',
    [string]$Ffmpeg = '',
    [switch]$WithVideo,
    [switch]$SkipRestart
)

$ErrorActionPreference = 'Stop'
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$script:Log = New-Object System.Collections.Generic.List[string]
$script:Cases = [ordered]@{}
$script:Stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')

foreach ($d in @($OutDir, (Join-Path $OutDir 'shot'), (Join-Path $OutDir 'video'), (Join-Path $OutDir 'log'))) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

function Write-Log {
    param([string]$Message)
    $line = '[' + (Get-Date).ToString('HH:mm:ss') + '] ' + $Message
    $script:Log.Add($line)
    Write-Host $line
}

function Write-JsonFile {
    param([string]$Path, $Data)
    [System.IO.File]::WriteAllText($Path, ($Data | ConvertTo-Json -Depth 12), $script:Utf8NoBom)
    return $Path
}

function Get-Sha256 {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

# ---------------- HTTP (no proxy, manual cookie handling) ----------------

function New-HttpClient {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseCookies = $false
    $handler.Proxy = $null
    $handler.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(90)
    return $client
}

function Invoke-Api {
    param(
        [string]$Method = 'GET',
        [string]$Path = '/',
        $Body = $null,
        [string]$Cookie = '',
        [string]$BaseUrl = ''
    )
    if (-not $BaseUrl) { $BaseUrl = $Base }
    $client = New-HttpClient
    try {
        $url = $BaseUrl.TrimEnd('/') + $Path
        $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::new($Method), $url)
        if ($Cookie) { $req.Headers.Add('Cookie', $Cookie) }
        if ($Body -ne $null) {
            $json = ($Body | ConvertTo-Json -Depth 8 -Compress)
            $req.Content = New-Object System.Net.Http.StringContent($json, [System.Text.Encoding]::UTF8, 'application/json')
        }
        $resp = $client.SendAsync($req).Result
        $text = $resp.Content.ReadAsStringAsync().Result
        $setCookie = @()
        $vals = $null
        if ($resp.Headers.TryGetValues('Set-Cookie', [ref]$vals)) { $setCookie = @($vals) }
        $parsed = $null
        try { $parsed = $text | ConvertFrom-Json } catch { $parsed = @{ _raw = $text.Substring(0, [Math]::Min(300, $text.Length)) } }
        return [ordered]@{
            status = [int]$resp.StatusCode
            set_cookie = $setCookie
            body = $parsed
            raw_len = $text.Length
        }
    } finally { $client.Dispose() }
}

function Get-SessionCookie {
    param($SetCookie)
    foreach ($c in @($SetCookie)) {
        $m = [regex]::Match([string]$c, 'session_id=([^;]+)')
        if ($m.Success) { return 'session_id=' + $m.Groups[1].Value }
    }
    return ''
}

function Invoke-Json {
    param([string]$Method, [string]$Path, $Body = $null, [string]$Cookie = '', [string]$BaseUrl = '')
    $r = Invoke-Api -Method $Method -Path $Path -Body $Body -Cookie $Cookie -BaseUrl $BaseUrl
    return $r
}

# ---------------- screenshots / video ----------------

function Save-Screenshot {
    param([string]$Path)
    try {
        Add-Type -AssemblyName System.Windows.Forms, System.Drawing
        $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
        $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose(); $bmp.Dispose()
        return (Get-Sha256 $Path)
    } catch {
        Write-Log ('screenshot failed: ' + $_.Exception.Message)
        return $null
    }
}

function Resolve-Ffmpeg {
    if ($Ffmpeg -and (Test-Path $Ffmpeg)) { return $Ffmpeg }
    $c = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $guess = Get-ChildItem 'C:\Users\*\AppData\Local\JianyingPro\Apps\*\ffmpeg.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($guess) { return $guess.FullName }
    return ''
}

$script:VideoProc = $null
$script:VideoFile = ''

function Start-RoundVideo {
    if (-not $WithVideo) { return }
    $exe = Resolve-Ffmpeg
    if (-not $exe) { Write-Log 'video: ffmpeg not found -> video element missing (verdict will be PARTIAL)'; return }
    $script:VideoFile = Join-Path $OutDir ('video\base-login-' + $script:Stamp + '.mp4')
    $args = @('-hide_banner', '-loglevel', 'error', '-f', 'gdigrab', '-framerate', '5', '-i', 'desktop',
              '-c:v', 'h264_mf', '-b:v', '1200k', '-pix_fmt', 'yuv420p', '-y', $script:VideoFile)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($args -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    $script:VideoProc = New-Object System.Diagnostics.Process
    $script:VideoProc.StartInfo = $psi
    [void]$script:VideoProc.Start()
    Write-Log ('video: recording -> ' + $script:VideoFile)
    Start-Sleep -Milliseconds 1500
}

function Stop-RoundVideo {
    if (-not $script:VideoProc) { return }
    try { $script:VideoProc.StandardInput.WriteLine('q'); $script:VideoProc.WaitForExit(15000) | Out-Null } catch {}
    if (-not $script:VideoProc.HasExited) { try { $script:VideoProc.Kill() } catch {} }
    Write-Log ('video: saved -> ' + $script:VideoFile)
}

# ---------------- app identity / process control ----------------

function Resolve-AppDir {
    if ($AppExe) { return (Split-Path $AppExe -Parent) }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\XCAGI'),
        (Join-Path $env:LOCALAPPDATA 'XCAGI'),
        'C:\Program Files\XCAGI',
        'C:\XCAGI'
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c 'XCAGI.exe')) { return $c }
    }
    $exe = Get-ChildItem -Path 'C:\' -Filter 'XCAGI.exe' -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) { return $exe.DirectoryName }
    return ''
}

function Get-AppProcesses {
    return @(Get-Process -Name 'XCAGI' -ErrorAction SilentlyContinue)
}

function Stop-App {
    $procs = Get-AppProcesses
    if ($procs.Count -eq 0) { return }
    Write-Log ('stopping app processes: ' + ($procs | ForEach-Object { $_.Id } | Sort-Object | Join-String -Separator ','))
    foreach ($p in $procs) { try { $null = $p.CloseMainWindow() } catch {} }
    Start-Sleep -Seconds 6
    foreach ($p in (Get-AppProcesses)) { try { Stop-Process -Id $p.Id -Force } catch {} }
    Start-Sleep -Seconds 3
    # the packaged backend may outlive the shell
    foreach ($p in @(Get-Process -Name 'xcagi-backend' -ErrorAction SilentlyContinue)) { try { Stop-Process -Id $p.Id -Force } catch {} }
    Start-Sleep -Seconds 2
}

function Wait-Health {
    param([int]$TimeoutSec = 180)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        try {
            $h = Invoke-Json -Method 'GET' -Path '/api/health'
            if ($h.status -eq 200) { return $h }
        } catch {}
        Start-Sleep -Seconds 3
    }
    return $null
}

function Start-App {
    param([string]$AppDir, [int]$DebugPort = 0)
    if (-not $AppDir) { throw 'app dir not resolved; pass -AppExe' }
    $exe = Join-Path $AppDir 'XCAGI.exe'
    if ($DebugPort -gt 0) {
        Start-Process -FilePath $exe -ArgumentList ('--remote-debugging-port=' + $DebugPort)
    } else {
        Start-Process -FilePath $exe
    }
    return (Wait-Health)
}

# ---------------- case helpers ----------------

function Add-Case {
    param([string]$Id, [string]$Title, [string]$Verdict, $Facts, [string]$Note = '', [string]$Shot = '')
    $script:Cases[$Id] = [ordered]@{
        id = $Id
        title = $Title
        verdict = $Verdict
        verify_time = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        facts = $Facts
        note = $Note
        screenshot = $Shot
    }
    Write-Log ($Id + ' verdict=' + $Verdict)
}

# ---------------- main ----------------

Write-Log '=== base-login Windows acceptance (this round) ==='
$appDir = Resolve-AppDir
$buildInfoPath = if ($appDir) { Join-Path $appDir 'resources\build-info.json' } else { '' }
if ($appDir -and -not (Test-Path $buildInfoPath)) {
    $alt = Join-Path $appDir 'build-info.json'
    if (Test-Path $alt) { $buildInfoPath = $alt }
}
$build = $null
if ($buildInfoPath -and (Test-Path $buildInfoPath)) { $build = Get-Content $buildInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json }
$exe = if ($appDir) { Join-Path $appDir 'XCAGI.exe' } else { '' }

$identity = [ordered]@{
    captured_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    host = $env:COMPUTERNAME
    user = $env:USERNAME
    os = (Get-CimInstance Win32_OperatingSystem).Caption + ' ' + (Get-CimInstance Win32_OperatingSystem).Version
    app_dir = $appDir
    app_exe = $exe
    app_exe_sha256 = Get-Sha256 $exe
    build_info = $build
    git_sha = if ($build) { $build.gitSha } else { '' }
    product_version = if ($build) { $build.version } else { '' }
    installer_path = $InstallerPath
    installer_sha256 = if ($InstallerPath) { Get-Sha256 $InstallerPath } else { '' }
}
$health0 = Wait-Health -TimeoutSec 20
$identity['health'] = $health0
Write-JsonFile (Join-Path $OutDir 'identity.json') $identity | Out-Null

Start-RoundVideo

# W1 未登录拒绝 (API level; the GUI state is captured by the operator in W2)
$me0 = Invoke-Json 'GET' '/api/auth/me'
$sv0 = Invoke-Json 'GET' '/api/auth/session/validate'
$w1ok = ($me0.body.valid -eq $false -and $sv0.body.valid -eq $false)
Add-Case 'W1' '未登录拒绝' ($(if ($w1ok) { 'PASS' } else { 'FAIL' })) @{
    me = $me0.body; validate = $sv0.body; me_status = $me0.status; validate_status = $sv0.status
} 'no session cookie -> protected endpoints report valid=false'

# W2 企业账号登录 (API assertions here; GUI screenshot/video from the operator)
$login = Invoke-Json 'POST' '/api/auth/login' @{ username = $Account; password = $Password; account_kind = 'enterprise'; totp_code = '' }
$cookie = Get-SessionCookie $login.set_cookie
$me1 = if ($cookie) { Invoke-Json 'GET' '/api/auth/me' -Cookie $cookie } else { $null }
$sv1 = if ($cookie) { Invoke-Json 'GET' '/api/auth/session/validate' -Cookie $cookie } else { $null }
$w2ok = ($login.status -eq 200 -and $cookie -and $me1.body.success -eq $true -and $me1.body.data.account_kind -eq 'enterprise')
Add-Case 'W2' '企业账号登录' ($(if ($w2ok) { 'PASS' } else { 'FAIL' })) @{
    login_status = $login.status; login_success = $login.body.success; session_cookie_present = [bool]$cookie
    account_kind = $me1.body.data.account_kind; username = $me1.body.data.user.username; tier = $me1.body.data.user.tier
    tenant_id = $me1.body.data.tenant_id; validate_valid = $sv1.body.valid
} 'API side of the login case; GUI login evidence (shot/video) is produced by the operator'

# W3 会话保持 (process restart keeps the same session valid)
if (-not $SkipRestart) {
    $beforeKind = $me1.body.data.account_kind
    Stop-App
    $h1 = Start-App -AppDir $appDir
    Start-Sleep -Seconds 8
    $me2 = Invoke-Json 'GET' '/api/auth/me' -Cookie $cookie
    $sv2 = Invoke-Json 'GET' '/api/auth/session/validate' -Cookie $cookie
    $w3ok = ($h1 -and $me2.body.success -eq $true -and $sv2.body.valid -eq $true -and $me2.body.data.account_kind -eq $beforeKind)
    Add-Case 'W3' '会话保持(进程重启)' ($(if ($w3ok) { 'PASS' } else { 'FAIL' })) @{
        health_after_restart = if ($h1) { $h1.status } else { $null }
        me_after_restart = $me2.body; validate_after_restart = $sv2.body
        same_session_cookie = $cookie
    } 'same session cookie still accepted after a real process restart'
    $shot3 = Join-Path $OutDir 'shot\W3-after-restart.png'
    Save-Screenshot $shot3 | Out-Null
}

# W4 安全退出 (API side; the operator captures the login page again in the GUI)
$me3 = Invoke-Json 'GET' '/api/auth/me' -Cookie $cookie
$logout = Invoke-Json 'POST' '/api/auth/logout' -Cookie $cookie
Start-Sleep -Seconds 2
$me4 = Invoke-Json 'GET' '/api/auth/me' -Cookie $cookie
$sv4 = Invoke-Json 'GET' '/api/auth/session/validate' -Cookie $cookie
$w4ok = ($me3.body.success -eq $true -and $logout.status -eq 200 -and $me4.body.valid -eq $false -and $sv4.body.valid -eq $false)
Add-Case 'W4' '安全退出' ($(if ($w4ok) { 'PASS' } else { 'FAIL' })) @{
    me_before = $me3.body; logout_status = $logout.status; logout_body = $logout.body
    me_after = $me4.body; validate_after = $sv4.body
} 'old session cookie is rejected right after logout'

# W5 边界负例
$bad = Invoke-Json 'POST' '/api/auth/login' @{ username = $Account; password = 'definitely-wrong-0001'; account_kind = 'enterprise' }
$admin = Invoke-Json 'POST' '/api/auth/login' @{ username = $Account; password = $Password; account_kind = 'admin' }
$empty = Invoke-Json 'POST' '/api/auth/login' @{ username = ''; password = '' }
$w5ok = ($bad.body.success -eq $false -and $admin.body.success -eq $false -and $empty.body.success -eq $false)
Add-Case 'W5' '边界负例' ($(if ($w5ok) { 'PASS' } else { 'FAIL' })) @{
    wrong_password = $bad.body; admin_kind_on_desktop = $admin.body; empty_credentials = $empty.body
} 'desktop rejects wrong credentials, admin account_kind and empty input'

# W6 Web 端同账户体系
$market = Invoke-Json 'POST' '/api/auth/login' @{ username = $Account; password = $Password } -BaseUrl $MarketBase
$w6ok = ($market.body.success -eq $true)
Add-Case 'W6' 'Web 端同账户体系' ($(if ($w6ok) { 'PASS' } else { 'FAIL' })) @{
    market_base = $MarketBase; status = $market.status; success = $market.body.success
    keys = @($market.body.PSObject.Properties.Name)
} 'the same enterprise account also logs in on the market (Web) endpoint'

Stop-RoundVideo

# ---------------- evidence packaging ----------------

$shotFiles = @()
foreach ($f in (Get-ChildItem (Join-Path $OutDir 'shot') -Filter '*.png' -ErrorAction SilentlyContinue)) {
    $shotFiles += [ordered]@{ name = $f.Name; bytes = $f.Length; sha256 = (Get-Sha256 $f.FullName); captured_at = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') }
}
$videoFile = $null
if ($script:VideoFile -and (Test-Path $script:VideoFile)) {
    $v = Get-Item $script:VideoFile
    $videoFile = [ordered]@{ path = $v.FullName; bytes = $v.Length; sha256 = (Get-Sha256 $v.FullName) }
}

$logPath = Join-Path $OutDir ('log\base-login-' + $script:Stamp + '.log')
[System.IO.File]::WriteAllText($logPath, ($script:Log -join [Environment]::NewLine) + [Environment]::NewLine, $script:Utf8NoBom)

$six = [ordered]@{
    screenshot = ($shotFiles.Count -gt 0)
    video = [bool]$videoFile
    log = (Test-Path $logPath)
    product_version = [bool]$identity.product_version
    app_sha = [bool]$identity.app_exe_sha256
    verify_time = $true
}
$sixComplete = ($six.Values -notcontains $false)

$summary = [ordered]@{
    feature = 'base-login'
    name = '登录与会话管理'
    platform = 'windows'
    round = $script:Stamp
    app_identity = $identity
    cases = $script:Cases
    evidence = [ordered]@{
        screenshots = $shotFiles
        video = $videoFile
        log = [ordered]@{ path = $logPath; bytes = (Get-Item $logPath).Length }
    }
    six_elements = $six
}
$caseVerdicts = @($script:Cases.Keys | ForEach-Object { $script:Cases[$_].verdict })
$failed = @($script:Cases.Keys | Where-Object { $script:Cases[$_].verdict -eq 'FAIL' })
if ($failed.Count -gt 0) {
    $summary['verdict'] = 'FAIL'
    $summary['first_real_breakpoint'] = $failed[0]
} elseif ($caseVerdicts -notcontains 'PASS') {
    $summary['verdict'] = 'BLOCKED'
} elseif (-not $sixComplete) {
    $summary['verdict'] = 'PARTIAL'
    $summary['verdict_reason'] = 'cases passed but the six evidence elements are incomplete: ' + (($six.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key }) -join ',')
} else {
    $summary['verdict'] = 'PASS'
}
$summary['generated_at'] = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')

Write-JsonFile (Join-Path $OutDir 'base-login-windows.json') $summary | Out-Null
Write-Host ''
Write-Host ('SUMMARY verdict=' + $summary.verdict + ' -> ' + (Join-Path $OutDir 'base-login-windows.json'))
Write-Host 'Return this whole folder (json + shot + video + log) to the Mac side; do not edit verdicts by hand.'