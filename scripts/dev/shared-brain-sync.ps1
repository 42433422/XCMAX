# shared-brain-sync.ps1 — Windows 端"自动共享大脑"守护
# 作用：把本地 Trae 记忆自动推送到生产知识库（persy-knowledge），并把其他设备写入的
#       共享记忆自动拉回本地镜像文件，实现四台设备智能体的认知自动对齐。
# 安装：计划任务登录自启 + 90 秒循环（见协议文档 docs/architecture/agent-shared-memory.md）
# 协议：push 端把本地记忆截断 3600 字后切成 8 个 ≤480 字槽位文档（单分块，可精确回读）；
#       pull 端按 metadata_filter 逐文档取回，排除本设备回声，重组写入本地镜像。

param(
    [string]$TunnelBase = "http://127.0.0.1:15100/api/knowledge/v1",
    [string]$Dataset = "persy-knowledge",
    [string]$ActorId = "agent-win32-trae",
    [string]$Device = "win32",
    [string]$MemoryDir = "$env:USERPROFILE\.trae-cn\memory\projects\-f--------5--42--p2-3ce3282e898e3e7ec177",
    [int]$IntervalSec = 90,
    [int]$Slots = 8,
    [int]$MaxPushChars = 3600,
    [int]$ChunkLimit = 480
)

$ErrorActionPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Jar = Join-Path $env:TEMP "shared-brain-csrf.jar"
$StateFile = Join-Path $MemoryDir ".shared-brain-state.json"
$MirrorFile = Join-Path $MemoryDir "shared_brain_kb.md"
$H = @{
    "X-Dataset-Actor-ID"    = $ActorId
    "X-Dataset-Tenant-ID"   = "default"
    "X-Dataset-Permissions" = "dataset.read,dataset.write"
}

function Get-Csrf {
    Remove-Item $Jar -Force -ErrorAction SilentlyContinue
    curl.exe -s -m 8 --noproxy "*" -c $Jar "$TunnelBase/health" @H -o NUL | Out-Null
    $line = Get-Content $Jar | Select-String "csrf_token"
    if ($line) { return (($line -split "`t") | Select-Object -Last 1) }
    return $null
}

function Invoke-KbPost([string]$Url, [hashtable]$ExtraHeaders, [string]$Json) {
    $csrf = Get-Csrf
    if (-not $csrf) { return $null }
    $all = $H + $ExtraHeaders
    curl.exe -s -m 25 --noproxy "*" -X POST $Url -H "X-CSRF-Token: $csrf" -b $Jar `
        -H "Content-Type: application/json" @all -d $Json
}

function Get-LocalBrainText {
    $parts = @()
    $pm = Join-Path $MemoryDir "project_memory.md"
    if (Test-Path $pm) {
        $raw = Get-Content $pm -Raw -Encoding UTF8
        # 去掉守护进程自管的指针块，避免回声
        $raw = $raw -replace "(?s)<!-- shared-brain-auto:BEGIN -->.*?<!-- shared-brain-auto:END -->", ""
        $parts += "## 本地 project_memory（最新在后）`n$raw"
    }
    $topics = Get-ChildItem $MemoryDir -Recurse -Filter "topics.md" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($topics) {
        $t = Get-Content $topics.FullName -Raw -Encoding UTF8
        if ($t.Length -gt 1800) { $t = $t.Substring($t.Length - 1800) }
        $parts += "## 最近会话 topics（尾部最新）`n$t"
    }
    $text = ($parts -join "`n`n") -replace "\r\n", "`n"
    if ($text.Length -gt $MaxPushChars) { $text = $text.Substring($text.Length - $MaxPushChars) }
    return $text
}

function Push-LocalBrain([string]$Text) {
    # 切槽位：每槽 ≤ChunkLimit 字，单分块文档可被 metadata_filter 精确回读
    $chunks = [math]::Ceiling($Text.Length / $ChunkLimit)
    if ($chunks -gt $Slots) { $chunks = $Slots }
    for ($i = 1; $i -le $Slots; $i++) {
        $docId = "agent-auto-$Device-part$i"
        if ($i -le $chunks) {
            $start = ($i - 1) * $ChunkLimit
            $len = [math]::Min($ChunkLimit, $Text.Length - $start)
            $slice = if ($len -gt 0) { $Text.Substring($start, $len) } else { "" }
            if ($slice) {
                $body = @{
                    source         = "agent-shared-memory/auto-$Device-part$i.md"
                    document_id    = $docId
                    text           = $slice
                    metadata       = @{ type = "agent-auto-sync"; device = $Device; part = $i; author = "shared-brain-daemon" }
                    tenant_id      = "default"
                    chunk_strategy = "fixed"
                } | ConvertTo-Json -Compress
                Invoke-KbPost "$TunnelBase/datasets/$Dataset/documents" @{} $body | Out-Null
            }
        }
        else {
            # 清空多余槽位（幂等）
            $csrf = Get-Csrf
            if ($csrf) {
                curl.exe -s -m 15 --noproxy "*" -X DELETE "$TunnelBase/datasets/$Dataset/documents/$docId" `
                    -H "X-CSRF-Token: $csrf" -b $Jar @H -o NUL | Out-Null
            }
        }
    }
}

function Pull-RemoteBrain {
    $statusRaw = curl.exe -s -m 10 --noproxy "*" "$TunnelBase/datasets/$Dataset/status?include_documents=true" @H
    $status = $statusRaw | ConvertFrom-Json
    if (-not $status.success) { return $null }
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# 共享大脑镜像（自动同步，勿手编；源=persy-knowledge）")
    [void]$sb.AppendLine("")
    foreach ($doc in $status.documents) {
        if ($doc.metadata.device -eq $Device -and $doc.metadata.type -eq "agent-auto-sync") { continue } # 排除回声
        $q = @{ query = "shared memory"; top_k = 1; metadata_filter = @{ document_id = $doc.document_id } } | ConvertTo-Json -Compress
        $resp = Invoke-KbPost "$TunnelBase/datasets/$Dataset/query" @{} $q
        if (-not $resp) { continue }
        $jr = $resp | ConvertFrom-Json
        if (-not $jr.success -or -not $jr.chunks -or $jr.chunks.Count -eq 0) { continue }
        $c = $jr.chunks | Sort-Object { $_.char_start } | Select-Object -First 1
        $dev = $doc.metadata.device; $auth = $doc.metadata.author
        [void]$sb.AppendLine("## [$dev/$auth] $($doc.document_id) (v$($doc.version))")
        [void]$sb.AppendLine($c.text)
        [void]$sb.AppendLine("")
    }
    return $sb.ToString()
}

# ---- 主循环 ----
while ($true) {
    try {
        $text = Get-LocalBrainText
        if ($text) {
            $hash = (Get-FileHash -InputStream ([System.IO.MemoryStream]::new([System.Text.Encoding]::UTF8.GetBytes($text))) -Algorithm MD5).Hash
            $state = if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { $null }
            if (-not $state -or $state.push_hash -ne $hash) {
                Push-LocalBrain $Text
                @{ push_hash = $hash; push_at = (Get-Date -Format o) } | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
            }
        }
        $mirror = Pull-RemoteBrain
        if ($mirror) {
            $mHash = (Get-FileHash -InputStream ([System.IO.MemoryStream]::new([System.Text.Encoding]::UTF8.GetBytes($mirror))) -Algorithm MD5).Hash
            $state = if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { $null }
            if (-not $state -or $state.mirror_hash -ne $mHash) {
                Set-Content $MirrorFile $mirror -Encoding UTF8
                $newState = @{ push_hash = $state.push_hash; mirror_hash = $mHash; mirror_at = (Get-Date -Format o) }
                $newState | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
            }
        }
    } catch { }
    Start-Sleep -Seconds $IntervalSec
}
