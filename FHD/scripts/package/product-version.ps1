# FHD/scripts/package/product-version.ps1
# Windows 侧产品版本解析的唯一出口 —— 与 bash 侧 deploy/lib/version.sh 对称。
# 放在 scripts/package 根下而非 lib/ 子目录：FHD/.gitignore:17 的 `lib/` 规则会漏掉新文件。
# 打包/发布/验收脚本不得再写死四段产品版本；显式传入的 -Version 优先（便于演练降级版本）。
function Resolve-ProductVersion {
  [CmdletBinding()]
  param([string]$Version = '')

  if ($Version) { return $Version.TrimStart('v', 'V') }

  $FhdRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
  $VersionFile = Join-Path $FhdRoot 'VERSION.md'
  $match = [regex]::Match(
    (Get-Content -LiteralPath $VersionFile -Raw),
    '\*\*XCAGI 稳定产品版本\*\*\s*\|\s*`(\d+\.\d+\.\d+\.\d+)`'
  )
  if (-not $match.Success) {
    throw ('FHD/VERSION.md 缺少「**XCAGI 稳定产品版本** | `x.y.z.w`」行，无法解析产品版本：' + $VersionFile)
  }
  return $match.Groups[1].Value
}
