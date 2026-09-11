# shared-brain-sync.ps1 - Windows auto shared-brain daemon (ASCII only for PS 5.1 safety)
# Push: local Trae memory -> KB as 8 single-chunk slot docs (agent-auto-<device>-partN).
# Pull: other devices' shared memories -> local mirror file shared_brain_kb.md.
# See docs/architecture/agent-shared-memory.md (protocol v2).

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
# Force UTF-8 both ways: [Console]::OutputEncoding decodes curl stdout (KB JSON),
# $OutputEncoding encodes args/stdin we hand to curl (push JSON with Chinese text).
# Without this, PS 5.1 on zh-CN uses GBK (CP936) and corrupts all non-ASCII text.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$Jar = Join-Path $env:TEMP "shared-brain-csrf.jar"
$StateFile = Join-Path $MemoryDir ".shared-brain-state.json"
$MirrorFile = Join-Path $MemoryDir "shared_brain_kb.md"
$HArgs = @(
    "-H", "X-Dataset-Actor-ID: $ActorId",
    "-H", "X-Dataset-Tenant-ID: default",
    "-H", "X-Dataset-Permissions: dataset.read,dataset.write"
)

function Get-Csrf {
    Remove-Item $Jar -Force -ErrorAction SilentlyContinue
    curl.exe -s -m 8 --noproxy "*" -c $Jar "$TunnelBase/health" @HArgs -o NUL | Out-Null
    $line = Get-Content $Jar -ErrorAction SilentlyContinue | Select-String "csrf_token"
    if ($line) { return (($line -split "`t") | Select-Object -Last 1) }
    return $null
}

function Invoke-KbPost([string]$Url, [string]$Json) {
    $csrf = Get-Csrf
    if (-not $csrf) { return $null }
    $out = curl.exe -s -m 25 --noproxy "*" -X POST $Url -H "X-CSRF-Token: $csrf" -b $Jar -H "Content-Type: application/json" @HArgs -d $Json
    if ($null -eq $out) { return $null }
    return ($out -join "`n")
}

function Get-HashOf([string]$Text) {
    $ms = [System.IO.MemoryStream]::new([System.Text.Encoding]::UTF8.GetBytes($Text))
    return (Get-FileHash -InputStream $ms -Algorithm MD5).Hash
}

function Get-LocalBrainText {
    $parts = @()
    $pm = Join-Path $MemoryDir "project_memory.md"
    if (Test-Path $pm) {
        $raw = Get-Content $pm -Raw -Encoding UTF8
        $raw = $raw -replace "(?s)<!-- shared-brain-auto:BEGIN -->.*?<!-- shared-brain-auto:END -->", ""
        $parts += "## local project_memory (newest last)`n$raw"
    }
    $topics = Get-ChildItem $MemoryDir -Recurse -Filter "topics.md" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($topics) {
        $t = Get-Content $topics.FullName -Raw -Encoding UTF8
        if ($t.Length -gt 1800) { $t = $t.Substring($t.Length - 1800) }
        $parts += "## recent topics (tail newest)`n$t"
    }
    $text = ($parts -join "`n`n") -replace "\r\n", "`n"
    if ($text.Length -gt $MaxPushChars) { $text = $text.Substring($text.Length - $MaxPushChars) }
    return $text
}

function Push-LocalBrain([string]$Text) {
    $chunks = [math]::Ceiling($Text.Length / $ChunkLimit)
    if ($chunks -gt $Slots) { $chunks = $Slots }
    for ($i = 1; $i -le $Slots; $i++) {
        $docId = "agent-auto-$Device-part$i"
        if ($i -le $chunks) {
            $start = ($i - 1) * $ChunkLimit
            $len = [math]::Min($ChunkLimit, $Text.Length - $start)
            $slice = ""
            if ($len -gt 0) { $slice = $Text.Substring($start, $len) }
            if ($slice) {
                $metaObj = @{ type = "agent-auto-sync"; device = $Device; part = $i; author = "shared-brain-daemon" }
                $bodyObj = @{ source = "agent-shared-memory/auto-$Device-part$i.md"; document_id = $docId; text = $slice; metadata = $metaObj; tenant_id = "default"; chunk_strategy = "fixed" }
                $body = $bodyObj | ConvertTo-Json -Compress
                Invoke-KbPost "$TunnelBase/datasets/$Dataset/documents" $body | Out-Null
            }
        }
        else {
            $csrf = Get-Csrf
            if ($csrf) {
                curl.exe -s -m 15 --noproxy "*" -X DELETE "$TunnelBase/datasets/$Dataset/documents/$docId" -H "X-CSRF-Token: $csrf" -b $Jar @HArgs -o NUL | Out-Null
            }
        }
    }
}

function Pull-RemoteBrain {
    $statusRaw = curl.exe -s -m 10 --noproxy "*" "$TunnelBase/datasets/$Dataset/status?include_documents=true" @HArgs
    $status = $statusRaw | ConvertFrom-Json
    if (-not $status.success) { return $null }

    # load existing mirror entries (cumulative merge; survives transient query failures)
    $entries = @{}
    if (Test-Path $MirrorFile) {
        $raw = Get-Content $MirrorFile -Raw -Encoding UTF8
        foreach ($m in [regex]::Matches($raw, "(?ms)^## \[([^\]]*)\] (\S+) \(v(\d+)( partial)?\)\s*?\r?\n(.*?)(?=^## \[|\z)")) {
            $entries[$m.Groups[2].Value] = @{
                header = $m.Groups[1].Value
                ver    = $m.Groups[3].Value
                text   = $m.Groups[5].Value.TrimEnd()
            }
        }
    }

    $liveIds = @{}
    foreach ($doc in $status.documents) {
        $md = $doc.metadata
        if ($md.device -eq $Device -and $md.type -eq "agent-auto-sync") { continue }
        $id = $doc.document_id
        $ver = [string]$doc.version
        $liveIds[$id] = $true
        if ($entries.ContainsKey($id) -and $entries[$id].ver -eq $ver) { continue }
        # fetch with 2 retries (query goes through the RAG agent and can transiently fail)
        $got = $null
        for ($attempt = 0; $attempt -lt 2 -and -not $got; $attempt++) {
            $filterObj = @{ document_id = $id }
            $qObj = @{ query = "shared memory"; top_k = 1; metadata_filter = $filterObj }
            $q = $qObj | ConvertTo-Json -Compress
            $resp = Invoke-KbPost "$TunnelBase/datasets/$Dataset/query" $q
            if (-not $resp) { continue }
            $jr = $null
            try { $jr = $resp | ConvertFrom-Json } catch { continue }
            if ($jr.success -and $jr.chunks -and @($jr.chunks).Count -gt 0) { $got = $jr }
        }
        if (-not $got) { continue }
        $c = @($got.chunks) | Sort-Object { $_.char_start } | Select-Object -First 1
        $dev = "?"; $auth = "?"
        if ($md) { if ($md.device) { $dev = $md.device }; if ($md.author) { $auth = $md.author } }
        $partial = ""
        if ($doc.text_length -gt 500) { $partial = " partial" }
        $entries[$id] = @{ header = "$dev/$auth"; ver = $ver; text = $c.text; partial = $partial }
    }

    # drop entries no longer present in KB
    foreach ($k in @($entries.Keys)) { if (-not $liveIds.ContainsKey($k)) { $entries.Remove($k) } }

    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# shared brain mirror (auto-synced; source=persy-knowledge)")
    [void]$sb.AppendLine("")
    foreach ($key in ($entries.Keys | Sort-Object)) {
        $e = $entries[$key]
        $p = ""; if ($e.partial) { $p = $e.partial }
        [void]$sb.AppendLine("## [$($e.header)] $key (v$($e.ver)$p)")
        [void]$sb.AppendLine($e.text)
        [void]$sb.AppendLine("")
    }
    return $sb.ToString()
}

while ($true) {
    try {
        $text = Get-LocalBrainText
        if ($text) {
            $hash = Get-HashOf $text
            $state = $null
            if (Test-Path $StateFile) { $state = Get-Content $StateFile -Raw | ConvertFrom-Json }
            $lastPush = $null; if ($state) { $lastPush = $state.push_hash }
            if ($lastPush -ne $hash) {
                Push-LocalBrain $Text
                @{ push_hash = $hash; push_at = (Get-Date -Format o) } | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
            }
        }
        $mirror = Pull-RemoteBrain
        if ($mirror) {
            $mHash = Get-HashOf $mirror
            $state = $null
            if (Test-Path $StateFile) { $state = Get-Content $StateFile -Raw | ConvertFrom-Json }
            $lastMirror = $null; if ($state) { $lastMirror = $state.mirror_hash }
            if ($lastMirror -ne $mHash) {
                Set-Content $MirrorFile $mirror -Encoding UTF8
                $newState = @{ push_hash = $state.push_hash; mirror_hash = $mHash; mirror_at = (Get-Date -Format o) }
                $newState | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
            }
        }
    } catch { }
    Start-Sleep -Seconds $IntervalSec
}
