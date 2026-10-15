# accept-base-login.ps1 - Windows real-machine acceptance for feature "base-login" (deng lu yu hui hua guan li).
# THIS ROUND ONLY (feature-acceptance-20260922). No product changes.
#
# ASCII-only source on purpose: Windows PowerShell 5.1 decodes files without a BOM as ANSI,
# so Chinese literals would turn into mojibake. Keep every string in this file ASCII.
#
# Feature: capability-center id `base-login` "deng lu yu hui hua guan li" (login + session mgmt).
# Case set (same as the macOS round, executed independently on Windows):
#   W1 not-logged-in rejection : GET /api/auth/me + /api/auth/session/validate without session cookie -> valid=false
#   W2 enterprise login        : API login + /api/auth/me (account_kind=enterprise); GUI evidence by the operator
#   W3 session persistence     : restart the app process, the same session cookie stays valid
#   W4 secure logout           : POST /api/auth/logout -> old cookie rejected; GUI returns to the login page
#   W5 boundary negatives      : wrong password / admin kind on desktop / empty credentials all rejected
#   W6 web shares the account  : the same account logs in on the market (Web) endpoint
#
# Six-element evidence contract (windows-evidence-1.0.0.5/rules.json):
#   screenshot + video + log + product_version + app_sha + verify_time -> PASS
#   missing any element -> PARTIAL. Never hand-edit verdicts.
#
# Output (this round, capability-center "per-platform" framework):
#   base-login-windows-run.json       the acceptance record the capability center reads.
#                                     Same structure as base-login-macos-run.json, with
#                                     platform="windows". Machine fields are generated here.
#   base-login-windows-identity.json  install/version/SHA reconnaissance snapshot (the raw capture).
#   shot\ video\ log\                 captured media + the run log.
#
# The record is written with media[].visual_review = "pending_review" on purpose: a human/AI must
# actually open each screenshot/video, then fill ONLY media[].visual_review, media[].visible_result
# and media[].reviewed_at for that file. Until then the capability center rejects the record and the
# Windows platform stays "pending" - nothing turns green on its own.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\accept-base-login.ps1 -SelfTest
#   powershell -ExecutionPolicy Bypass -File .\accept-base-login.ps1 -WithVideo `
#     -InstallerPath "C:\...\XCAGI-Enterprise-Setup-1.0.0.5-x64-unsigned.exe" `
#     -OutDir "C:\XCAGI-acceptance\feature-base-login"
#
# Operator (Windows-side agent UI automation) must place these screenshots into <OutDir>\shot\:
#   W2-login-page.png, W2-login-workspace.png, W4-login-page-again.png

param(
    [string]$Base = 'http://127.0.0.1:17500',
    # Credentials come from the environment (XCAGI_TEST_USER / XCAGI_TEST_PASS) or explicit
    # parameters. Do NOT hardcode a password in this file: the repo is public.
    [string]$Account = $(if ($env:XCAGI_TEST_USER) { $env:XCAGI_TEST_USER } else { 'SUNBIRD' }),
    [string]$Password = $env:XCAGI_TEST_PASS,
    [string]$MarketBase = 'https://xiu-ci.com',
    [string]$OutDir = (Join-Path $env:TEMP 'win-evidence\feature-base-login'),
    # Repo-relative directory the returned evidence will live in. Used to write media[].path in the
    # acceptance record, so the returning side does not have to hand-edit paths.
    [string]$RepoRelDir = 'FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login/windows',
    [string]$AppExe = '',
    [string]$InstallerPath = '',
    [string]$Ffmpeg = '',
    [switch]$WithVideo,
    [switch]$SkipRestart,
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 does not load System.Net.Http by default.
try { Add-Type -AssemblyName System.Net.Http -ErrorAction Stop } catch { }
if (-not ('System.Net.Http.HttpClient' -as [type])) {
    Write-Host 'FATAL: System.Net.Http is unavailable. Run under Windows PowerShell 5.1 with .NET 4.5+ or PowerShell 7.'
    exit 2
}
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
    if (-not $Path) { return $null }
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

function Get-CookieFingerprint {
    # A raw session cookie must never enter the evidence: the record is committed to a public repo.
    # A truncated hash proves "the very same cookie value was reused" without leaking the value.
    param([string]$Cookie)
    if (-not $Cookie) { return '' }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Cookie)
        $hex = ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLower()
        return $hex.Substring(0, 16)
    } finally { $sha.Dispose() }
}

# ---------------- HTTP (no proxy, manual cookie handling) ----------------

function Invoke-Api {
    param(
        [string]$Method = 'GET',
        [string]$Path = '/',
        $Body = $null,
        [string]$Cookie = '',
        [string]$BaseUrl = ''
    )
    if (-not $BaseUrl) { $BaseUrl = $Base }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseCookies = $false
    $handler.Proxy = $null
    $handler.UseProxy = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(90)
    try {
        $url = $BaseUrl.TrimEnd('/') + $Path
        $httpMethod = New-Object System.Net.Http.HttpMethod($Method)
        $req = New-Object System.Net.Http.HttpRequestMessage($httpMethod, $url)
        if ($Cookie) { [void]$req.Headers.Add('Cookie', $Cookie) }
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

function Protect-SetCookie {
    # Credential values (session/CSRF tokens) must never reach the record verbatim. The macOS
    # side keeps the same policy: base-login-macos-raw-redacted.json masks every cookie value
    # while leaving the rest of the capture byte-for-byte intact. Only the value before the
    # first ';' is replaced; the attribute list (Path, SameSite, ...) is kept so the record
    # still shows that a cookie was issued.
    # Never call this on the cookie used for authentication: W2/W3/W4 reuse the live value.
    # ASCII-only on purpose (see the file header).
    param($SetCookie)
    $out = @()
    foreach ($c in @($SetCookie)) {
        $s = [string]$c
        $i = $s.IndexOf(';')
        if ($i -lt 0) { $out += '<redacted>'; continue }
        $head = $s.Substring(0, $i)
        $eq = $head.IndexOf('=')
        $name = $head
        if ($eq -ge 0) { $name = $head.Substring(0, $eq) }
        $out += ($name + '=<redacted>' + $s.Substring($i))
    }
    return ,$out
}

function Get-SessionCookie {
    param($SetCookie)
    foreach ($c in @($SetCookie)) {
        $m = [regex]::Match([string]$c, 'session_id=([^;]+)')
        if ($m.Success) { return 'session_id=' + $m.Groups[1].Value }
    }
    return ''
}

function Get-BodyField {
    param($Body, [string]$Name)
    if ($null -eq $Body) { return $null }
    $prop = $Body.PSObject.Properties[$Name]
    if ($prop) { return $prop.Value }
    return $null
}

# ---------------- screenshots / video ----------------

function Save-Screenshot {
    param([string]$Path)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
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
    try {
        $script:VideoProc.StandardInput.WriteLine('q')
        $script:VideoProc.WaitForExit(15000) | Out-Null
    } catch { }
    if (-not $script:VideoProc.HasExited) { try { $script:VideoProc.Kill() } catch { } }
    Write-Log ('video: saved -> ' + $script:VideoFile)
}

# ---------------- app identity / process control ----------------

function Resolve-AppDir {
    if ($AppExe) { return (Split-Path $AppExe -Parent) }
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\XCAGI'))
        $candidates.Add((Join-Path $env:LOCALAPPDATA 'XCAGI'))
    }
    if ($env:PROGRAMFILES) { $candidates.Add((Join-Path $env:PROGRAMFILES 'XCAGI')) }
    $candidates.Add('C:\XCAGI')
    $candidates.Add('C:\XCAGI-evidence-1.0.0.5\app')
    foreach ($c in $candidates) {
        if ($c -and (Test-Path ($c.TrimEnd('\') + '\XCAGI.exe'))) { return $c }
    }
    if (Test-Path 'C:\') {
        $exe = Get-ChildItem -Path 'C:\' -Filter 'XCAGI.exe' -Recurse -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($exe) { return $exe.DirectoryName }
    }
    return ''
}

function Wait-AuthRoute {
    # /api/health can answer 200 before the auth router is mounted (fresh-install race).
    # Wait until /api/auth/me returns the expected envelope (a `valid` field) so W1 is not
    # judged against a not-yet-mounted route ("resource not found" is not a rejection proof).
    param([int]$TimeoutSec = 180)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        try {
            $r = Invoke-Api -Method 'GET' -Path '/api/auth/me'
            $v = Get-BodyField $r.body 'valid'
            if ($null -ne $v) { return $r }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $null
}

function Get-AppProcesses {
    return @(Get-Process -Name 'XCAGI' -ErrorAction SilentlyContinue)
}

function Stop-App {
    $procs = Get-AppProcesses
    if ($procs.Count -eq 0) { return }
    $ids = @($procs | ForEach-Object { $_.Id } | Sort-Object)
    Write-Log ('stopping app processes: ' + ($ids -join ','))
    foreach ($p in $procs) { try { [void]$p.CloseMainWindow() } catch { } }
    Start-Sleep -Seconds 6
    foreach ($p in (Get-AppProcesses)) { try { Stop-Process -Id $p.Id -Force } catch { } }
    Start-Sleep -Seconds 3
    foreach ($p in @(Get-Process -Name 'xcagi-backend' -ErrorAction SilentlyContinue)) {
        try { Stop-Process -Id $p.Id -Force } catch { }
    }
    Start-Sleep -Seconds 2
}

function Wait-Health {
    param([int]$TimeoutSec = 180)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $end) {
        try {
            $h = Invoke-Api -Method 'GET' -Path '/api/health'
            if ($h.status -eq 200) { return $h }
        } catch { }
        Start-Sleep -Seconds 3
    }
    return $null
}

function Start-App {
    param([string]$AppDir, [int]$DebugPort = 0)
    if (-not $AppDir) { throw 'app dir not resolved; pass -AppExe' }
    $exe = $AppDir.TrimEnd('\') + '\XCAGI.exe'
    if ($DebugPort -gt 0) {
        Start-Process -FilePath $exe -ArgumentList ('--remote-debugging-port=' + $DebugPort)
    } else {
        Start-Process -FilePath $exe
    }
    return (Wait-Health)
}

function Wait-AppWindow {
    # Backend health comes back long before the renderer has settled. Measured on this build
    # (1.0.0.5 / 4e172943): the window exists at ~8s as the splash (title "XCAGI"), sits on
    # the login route around 18-26s while the stored session is resolved (title "XCAGI <dot>
    # <login word>"), and only then paints the authenticated shell, whose title ends in
    # " - XCAGI". Capturing at a fixed 8s after health produced an empty loading frame that
    # cannot serve as W3 evidence, so wait for the authenticated-shell title.
    # ASCII-only on purpose (see the file header): the shell title is matched by its ASCII
    # suffix, never by a Chinese literal.
    param([int]$TimeoutSec = 180)
    $end = (Get-Date).AddSeconds($TimeoutSec)
    $seen = New-Object System.Collections.Generic.List[string]
    while ((Get-Date) -lt $end) {
        $w = Get-Process -Name 'XCAGI' -ErrorAction SilentlyContinue |
             Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle } |
             Select-Object -First 1
        $title = ''
        if ($w) { $title = [string]$w.MainWindowTitle }
        if ($title) {
            if ($seen.Count -eq 0 -or $seen[$seen.Count - 1] -ne $title) {
                $seen.Add($title)
                Write-Log ('window title: "' + $title + '"')
            }
            if ($title -like '*- XCAGI') {
                Start-Sleep -Seconds 3
                return $title
            }
        }
        Start-Sleep -Seconds 2
    }
    Write-Log ('window wait timed out; titles seen: ' + ($seen -join ' -> '))
    return ''
}

# ---------------- case helpers ----------------

# The capability center validates every case as input/actions/expected/observed + result.
# input/actions/expected are authored here (they describe what this script really does);
# observed is derived from the facts of the actual run, never typed by hand.
$script:CaseSpec = @{
    'W1' = @{
        input = 'No session cookie: GET /api/auth/me and GET /api/auth/session/validate; plus the current GUI state.'
        actions = 'Call both protected endpoints without a Cookie header, then read the rendered UI state.'
        expected = 'Both endpoints report valid=false, and the window stays on the login page (no workspace).'
    }
    'W2' = @{
        input = 'Enterprise credentials via POST /api/auth/login (account_kind=enterprise).'
        actions = 'Login, keep the returned session_id cookie, then GET /api/auth/me with that cookie.'
        expected = 'login returns 200 with success=true, a session_id cookie is issued, and me reports success=true with account_kind=enterprise.'
    }
    'W3' = @{
        input = 'The session cookie obtained in W2, reused after killing and restarting the XCAGI processes.'
        actions = 'Close the app, wait for the backend to stop, start XCAGI.exe again, wait for health, then call me + session/validate with the same cookie.'
        expected = 'Backend health is 200 and the same session is still valid (me.success=true, validate.valid=true).'
    }
    'W4' = @{
        input = 'An authenticated session cookie; POST /api/auth/logout followed by reuse of that cookie.'
        actions = 'Confirm me succeeds before logout, POST /api/auth/logout, then call me + session/validate with the old cookie.'
        expected = 'Logout returns 200 and the old cookie is rejected right after (both responses report valid=false).'
    }
    'W5' = @{
        input = 'Three rejected logins: wrong password, account_kind=admin on the desktop endpoint, and empty credentials.'
        actions = 'POST each variant to /api/auth/login and read the success flag of every response.'
        expected = 'All three attempts return success=false.'
    }
    'W6' = @{
        input = 'The same enterprise account against the market (Web) endpoint https://xiu-ci.com/api/auth/login.'
        actions = 'POST username/password to the market login endpoint and read ok / access_token.'
        expected = 'ok=true or an access_token is issued, proving the desktop and Web share one account system.'
    }
}

function Add-Case {
    param([string]$Id, [string]$Title, [string]$Verdict, $Facts, [string]$Note = '')
    $spec = $script:CaseSpec[$Id]
    $result = 'failed'
    if ($Verdict -eq 'PASS') { $result = 'passed' }
    $script:Cases[$Id] = [ordered]@{
        id = $Id
        title = $Title
        input = [string]$spec.input
        actions = [string]$spec.actions
        expected = [string]$spec.expected
        observed = ($Facts | ConvertTo-Json -Depth 6 -Compress)
        result = $result
        verdict = $Verdict
        verify_time = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        facts = $Facts
        note = $Note
    }
    Write-Log ($Id + ' verdict=' + $Verdict)
}

# ---------------- identity ----------------

function Get-BuildInfo {
    param([string]$AppDir)
    if (-not $AppDir) { return $null }
    $paths = @(
        ($AppDir.TrimEnd('\') + '\resources\build-info.json'),
        ($AppDir.TrimEnd('\') + '\build-info.json')
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) }
    }
    return $null
}

function Get-Identity {
    param([string]$AppDir)
    $build = Get-BuildInfo -AppDir $AppDir
    $exe = ''
    if ($AppDir) { $exe = $AppDir.TrimEnd('\') + '\XCAGI.exe' }
    $osCaption = ''
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $osCaption = ([string]$os.Caption) + ' ' + ([string]$os.Version)
    } catch { }
    $gitSha = ''
    $version = ''
    if ($build) {
        $gitSha = [string]$build.gitSha
        $version = [string]$build.version
    }
    $installerSha = ''
    if ($InstallerPath) { $installerSha = [string](Get-Sha256 $InstallerPath) }
    return [ordered]@{
        captured_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        host = $env:COMPUTERNAME
        user = $env:USERNAME
        os = $osCaption
        app_dir = $AppDir
        app_exe = $exe
        app_exe_sha256 = [string](Get-Sha256 $exe)
        build_info = $build
        git_sha = $gitSha
        product_version = $version
        installer_path = $InstallerPath
        installer_sha256 = $installerSha
    }
}

# ---------------- main ----------------

Write-Log '=== base-login Windows acceptance (this round) ==='
Write-Log ('account=' + $Account + ' (password supplied: ' + [bool]$Password + ')')
$appDir = Resolve-AppDir
Write-Log ('app_dir=' + $appDir)
$identity = Get-Identity -AppDir $appDir
$health0 = Wait-Health -TimeoutSec 25
$healthStatus = $null
if ($health0) { $healthStatus = $health0.status }
if ($health0) { $health0['set_cookie'] = Protect-SetCookie -SetCookie $health0['set_cookie'] }
$identity['health'] = $health0
Write-JsonFile (Join-Path $OutDir 'base-login-windows-identity.json') $identity | Out-Null
Write-Log ('identity: git_sha=' + $identity.git_sha + ' version=' + $identity.product_version + ' health=' + $healthStatus)

if ($health0) {
    Write-Log 'waiting for the auth route to be mounted ...'
    $authReady = Wait-AuthRoute
    $authReadyOk = [bool]$authReady
    Write-Log ('auth route ready: ' + $authReadyOk)
    $identity['auth_route_ready'] = $authReadyOk
    Write-JsonFile (Join-Path $OutDir 'base-login-windows-identity.json') $identity | Out-Null
}

if ($SelfTest) {
    Write-Host ''
    Write-Host '--- SELF TEST ---'
    Write-Host ('app_dir          : ' + $appDir)
    Write-Host ('exe              : ' + $identity.app_exe)
    Write-Host ('exe_sha256       : ' + $identity.app_exe_sha256)
    Write-Host ('git_sha          : ' + $identity.git_sha)
    Write-Host ('product_version  : ' + $identity.product_version)
    Write-Host ('installer_sha256 : ' + $identity.installer_sha256)
    Write-Host ('backend health   : ' + $healthStatus)
    Write-Host ('app processes    : ' + (@(Get-AppProcesses).Count))
    Write-Host ('ffmpeg           : ' + (Resolve-Ffmpeg))
    Write-Host ('out_dir          : ' + $OutDir)
    $probe = Invoke-Api -Method 'GET' -Path '/api/auth/me'
    Write-Host ('api /api/auth/me : status=' + $probe.status + ' valid=' + (Get-BodyField $probe.body 'valid'))
    Write-Host '--- SELF TEST DONE (no case ran, nothing mutated except base-login-windows-identity.json) ---'
    exit 0
}

# The acceptance cases need a real enterprise credential. -SelfTest above stays credential-free.
if (-not $Password) {
    Write-Host 'FATAL: no credential supplied.'
    Write-Host 'Set XCAGI_TEST_PASS (and optionally XCAGI_TEST_USER) or pass -Password, then re-run.'
    Write-Host 'This file intentionally does not contain the password (public repo).'
    exit 2
}

Start-RoundVideo

# W1 not-logged-in rejection (API level; GUI state captured by the operator in W2)
$me0 = Invoke-Api -Method 'GET' -Path '/api/auth/me'
$sv0 = Invoke-Api -Method 'GET' -Path '/api/auth/session/validate'
$w1ok = ((Get-BodyField $me0.body 'valid') -eq $false) -and ((Get-BodyField $sv0.body 'valid') -eq $false)
$w1verdict = 'FAIL'
if ($w1ok) { $w1verdict = 'PASS' }
$w1facts = [ordered]@{
    me = $me0.body
    validate = $sv0.body
    me_status = $me0.status
    validate_status = $sv0.status
}
Add-Case 'W1' 'no-session rejection' $w1verdict $w1facts 'no session cookie -> protected endpoints report valid=false'

# W2 enterprise login (API assertions here; GUI screenshot/video from the operator)
$loginBody = @{ username = $Account; password = $Password; account_kind = 'enterprise'; totp_code = '' }
$login = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body $loginBody
$cookie = Get-SessionCookie $login.set_cookie
$me1 = $null
$sv1 = $null
if ($cookie) {
    $me1 = Invoke-Api -Method 'GET' -Path '/api/auth/me' -Cookie $cookie
    $sv1 = Invoke-Api -Method 'GET' -Path '/api/auth/session/validate' -Cookie $cookie
}
$loginSuccess = Get-BodyField $login.body 'success'
$me1Success = $null
$me1Kind = $null
$me1User = $null
$me1Tier = $null
$me1Tenant = $null
$sv1Valid = $null
if ($me1) {
    $me1Success = Get-BodyField $me1.body 'success'
    $data = Get-BodyField $me1.body 'data'
    if ($data) {
        $me1Kind = Get-BodyField $data 'account_kind'
        $me1Tier = Get-BodyField $data 'tier'
        $me1Tenant = Get-BodyField $data 'tenant_id'
        $userObj = Get-BodyField $data 'user'
        if ($userObj) { $me1User = Get-BodyField $userObj 'username' }
    }
}
if ($sv1) { $sv1Valid = Get-BodyField $sv1.body 'valid' }
$w2ok = ($login.status -eq 200) -and ($loginSuccess -eq $true) -and [bool]$cookie -and ($me1Success -eq $true) -and ($me1Kind -eq 'enterprise')
$w2verdict = 'FAIL'
if ($w2ok) { $w2verdict = 'PASS' }
$w2facts = [ordered]@{
    login_status = $login.status
    login_success = $loginSuccess
    session_cookie_present = [bool]$cookie
    account_kind = $me1Kind
    username = $me1User
    tier = $me1Tier
    tenant_id = $me1Tenant
    validate_valid = $sv1Valid
}
Add-Case 'W2' 'enterprise login (API side)' $w2verdict $w2facts 'GUI login evidence (shot/video) is produced by the operator'

# W3 session persistence (real process restart keeps the same session valid)
if (-not $SkipRestart) {
    Stop-App
    $h1 = Start-App -AppDir $appDir
    # Health is not the same as "the UI is up": wait for the renderer to settle so the W3
    # screenshot shows the real post-restart screen instead of an empty loading frame.
    $w3Title = Wait-AppWindow
    $me2 = Invoke-Api -Method 'GET' -Path '/api/auth/me' -Cookie $cookie
    $sv2 = Invoke-Api -Method 'GET' -Path '/api/auth/session/validate' -Cookie $cookie
    $me2Success = Get-BodyField $me2.body 'success'
    $sv2Valid = Get-BodyField $sv2.body 'valid'
    $healthAfter = $null
    if ($h1) { $healthAfter = $h1.status }
    $w3ok = [bool]$h1 -and ($me2Success -eq $true) -and ($sv2Valid -eq $true)
    $w3verdict = 'FAIL'
    if ($w3ok) { $w3verdict = 'PASS' }
    $w3facts = [ordered]@{
        health_after_restart = $healthAfter
        window_title_after_restart = $w3Title
        me_after_restart = $me2.body
        validate_after_restart = $sv2.body
        # Never record the raw cookie value: this record is committed to a public repo.
        session_cookie_reused = [bool]$cookie
        session_cookie_fingerprint = (Get-CookieFingerprint $cookie)
    }
    Add-Case 'W3' 'session persistence (process restart)' $w3verdict $w3facts 'same session cookie still accepted after a real process restart'
    $shot3 = Join-Path $OutDir 'shot\W3-after-restart.png'
    Save-Screenshot $shot3 | Out-Null
}

# W4 secure logout (API side; the operator captures the login page again in the GUI)
$me3 = Invoke-Api -Method 'GET' -Path '/api/auth/me' -Cookie $cookie
$logout = Invoke-Api -Method 'POST' -Path '/api/auth/logout' -Cookie $cookie
Start-Sleep -Seconds 2
$me4 = Invoke-Api -Method 'GET' -Path '/api/auth/me' -Cookie $cookie
$sv4 = Invoke-Api -Method 'GET' -Path '/api/auth/session/validate' -Cookie $cookie
$me3Success = Get-BodyField $me3.body 'success'
$me4Valid = Get-BodyField $me4.body 'valid'
$sv4Valid = Get-BodyField $sv4.body 'valid'
$w4ok = ($me3Success -eq $true) -and ($logout.status -eq 200) -and ($me4Valid -eq $false) -and ($sv4Valid -eq $false)
$w4verdict = 'FAIL'
if ($w4ok) { $w4verdict = 'PASS' }
$w4facts = [ordered]@{
    me_before = $me3.body
    logout_status = $logout.status
    logout_body = $logout.body
    me_after = $me4.body
    validate_after = $sv4.body
}
Add-Case 'W4' 'secure logout' $w4verdict $w4facts 'old session cookie is rejected right after logout'

# W5 boundary negatives
$badBody = @{ username = $Account; password = ('wrong-' + $script:Stamp); account_kind = 'enterprise' }
$bad = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body $badBody
$adminBody = @{ username = $Account; password = $Password; account_kind = 'admin' }
$admin = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body $adminBody
$emptyBody = @{ username = ''; password = '' }
$empty = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body $emptyBody
$w5ok = ((Get-BodyField $bad.body 'success') -eq $false) -and ((Get-BodyField $admin.body 'success') -eq $false) -and ((Get-BodyField $empty.body 'success') -eq $false)
$w5verdict = 'FAIL'
if ($w5ok) { $w5verdict = 'PASS' }
$w5facts = [ordered]@{
    wrong_password = $bad.body
    admin_kind_on_desktop = $admin.body
    empty_credentials = $empty.body
}
Add-Case 'W5' 'boundary negatives' $w5verdict $w5facts 'desktop rejects wrong credentials, admin account_kind and empty input'

# W6 web shares the same account system
$marketBody = @{ username = $Account; password = $Password }
$market = Invoke-Api -Method 'POST' -Path '/api/auth/login' -Body $marketBody -BaseUrl $MarketBase
$marketOk = Get-BodyField $market.body 'ok'
$marketToken = Get-BodyField $market.body 'access_token'
$marketDesktop = Get-BodyField $market.body 'desktop_access'
$marketUser = $null
$marketUserObj = Get-BodyField $market.body 'user'
if ($marketUserObj) { $marketUser = Get-BodyField $marketUserObj 'username' }
$w6ok = ($marketOk -eq $true) -or [bool]$marketToken
$w6verdict = 'FAIL'
if ($w6ok) { $w6verdict = 'PASS' }
$w6facts = [ordered]@{
    market_base = $MarketBase
    status = $market.status
    ok = $marketOk
    has_access_token = [bool]$marketToken
    user = $marketUser
    desktop_access = $marketDesktop
}
Add-Case 'W6' 'web shares the account system' $w6verdict $w6facts 'the same enterprise account also logs in on the market (Web) endpoint'

Stop-RoundVideo

# ---------------- evidence packaging ----------------

$shotFiles = @()
$shotDir = Join-Path $OutDir 'shot'
foreach ($f in @(Get-ChildItem $shotDir -Filter '*.png' -ErrorAction SilentlyContinue)) {
    $shotFiles += [ordered]@{
        name = $f.Name
        bytes = $f.Length
        sha256 = (Get-Sha256 $f.FullName)
        captured_at = $f.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    }
}
# NOTE: this local variable must NOT be named $videoFile: PowerShell variable names are
# case-insensitive, so "$videoFile = $null" also clears $script:VideoFile, which made the
# guard below always false and silently dropped the recording from six_elements/media[].
$videoEntry = $null
if ($script:VideoFile -and (Test-Path $script:VideoFile)) {
    $v = Get-Item $script:VideoFile
    $videoEntry = [ordered]@{ path = $v.FullName; bytes = $v.Length; sha256 = (Get-Sha256 $v.FullName) }
}

$logPath = Join-Path $OutDir ('log\base-login-' + $script:Stamp + '.log')
$logText = ($script:Log -join [Environment]::NewLine) + [Environment]::NewLine
[System.IO.File]::WriteAllText($logPath, $logText, $script:Utf8NoBom)

$six = [ordered]@{
    screenshot = ($shotFiles.Count -gt 0)
    video = [bool]$videoEntry
    log = (Test-Path $logPath)
    product_version = [bool]$identity.product_version
    app_sha = [bool]$identity.app_exe_sha256
    verify_time = $true
}
$sixMissing = @($six.Keys | Where-Object { -not $six[$_] })
$caseIds = @($script:Cases.Keys)
$failed = @($caseIds | Where-Object { $script:Cases[$_].verdict -eq 'FAIL' })
$passCount = @($caseIds | Where-Object { $script:Cases[$_].verdict -eq 'PASS' }).Count

$verdict = 'BLOCKED'
$verdictReason = ''
if ($failed.Count -gt 0) {
    $verdict = 'FAIL'
} elseif ($passCount -eq $caseIds.Count) {
    if ($sixMissing.Count -eq 0) { $verdict = 'PASS' } else { $verdict = 'PARTIAL' }
    if ($sixMissing.Count -gt 0) {
        $verdictReason = 'cases passed but six evidence elements incomplete: ' + ($sixMissing -join ',')
    }
} else {
    $verdict = 'BLOCKED'
}

$firstBreak = $null
if ($failed.Count -gt 0) { $firstBreak = $failed[0] }

# ---------------- capability-center record (same structure as base-login-macos-run.json) ----------------

$repoDir = $RepoRelDir.TrimEnd('/')
$caseList = @()
foreach ($cid in $caseIds) { $caseList += $script:Cases[$cid] }

$media = @()
foreach ($s in $shotFiles) {
    $media += [ordered]@{
        feature = 'base-login'
        path = $repoDir + '/shot/' + $s.name
        sha256 = $s.sha256
        # Left unreviewed on purpose: a human/AI must open the file and write what is visible.
        # The capability center rejects unreviewed media, so nothing turns green on its own.
        visual_review = 'pending_review'
        visible_result = ''
        reviewed_at = ''
    }
}
if ($videoEntry) {
    $media += [ordered]@{
        feature = 'base-login'
        path = $repoDir + '/video/' + (Split-Path $videoEntry.path -Leaf)
        sha256 = $videoEntry.sha256
        visual_review = 'pending_review'
        visible_result = ''
        reviewed_at = ''
    }
}

$recordStatus = 'failed'
if ($verdict -eq 'PASS') { $recordStatus = 'passed' }

$warnings = @()
if ([string]$identity.git_sha -notmatch '^[0-9a-fA-F]{40}$') {
    $warnings += ('app_git_sha is not a full 40-hex commit ("' + [string]$identity.git_sha + '"): the capability center will not accept this record until it is resolved.')
}
if ($media.Count -eq 0) {
    $warnings += 'no media captured: nothing can be bound to the windows platform.'
}
foreach ($w in $warnings) { Write-Log ('WARN: ' + $w) }

$record = [ordered]@{
    _comment = 'Windows real-machine acceptance record for the capability center (feature-acceptance format, same structure as base-login-macos-run.json). Generated by accept-base-login.ps1; only media[].visual_review / media[].visible_result / media[].reviewed_at may be filled in, and only after actually viewing that file.'
    kind = 'feature-acceptance'
    feature = 'base-login'
    platform = 'windows'
    status = $recordStatus
    app_git_sha = ([string]$identity.git_sha).ToLower()
    app_version = [string]$identity.product_version
    verified_at = (Get-Date).ToString('yyyy-MM-dd')
    reviewed_at = ''
    passed = $passCount
    failed = $failed.Count
    round = $script:Stamp
    generated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    verdict = $verdict
    verdict_reason = $verdictReason
    first_real_breakpoint = $firstBreak
    six_elements = $six
    six_missing = @($sixMissing)
    app_identity = $identity
    log = [ordered]@{
        path = $repoDir + '/log/' + (Split-Path $logPath -Leaf)
        bytes = (Get-Item $logPath).Length
        sha256 = (Get-Sha256 $logPath)
    }
    media = $media
    cases = $caseList
    warnings = $warnings
}

$recordPath = Join-Path $OutDir 'base-login-windows-run.json'
Write-JsonFile $recordPath $record | Out-Null
Write-Host ''
Write-Host ('SUMMARY verdict=' + $verdict + ' status=' + $recordStatus + ' cases=' + $passCount + '/' + $caseIds.Count + ' media=' + $media.Count)
Write-Host ('RECORD -> ' + $recordPath)
Write-Host 'Return this whole folder (record + identity + shot + video + log) to the Mac side; do not hand-edit verdicts or machine fields.'
Write-Host 'Before returning: open every shot/video, then fill ONLY media[].visual_review (accepted), media[].visible_result (what you actually saw) and media[].reviewed_at.'
