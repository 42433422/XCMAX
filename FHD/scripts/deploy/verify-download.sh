#!/usr/bin/env bash
# 验收 XCAGI 下载清单 manifest.json 中所有 URL 的可下载性与完整性。
#
# 验收项:
#   1. HTTP 状态码 200
#   2. Content-Length 与 manifest 中的 size 一致
#   3. SHA256 与 manifest 中的 sha256 一致
#   4. 文件 magic 是有效安装包(PE MZ / DMG koly / APK PK)
#   5. personal/enterprise SKU 文件名未混淆
#
# 用法:
#   bash scripts/deploy/verify-download.sh manifest.json
#   bash scripts/deploy/verify-download.sh manifest.json --skip-sha256  # 跳过 SHA(快速检查)
#
# 退出码:
#   0 = 全部通过
#   1 = 至少一项失败
#   2 = 参数错误 / manifest 解析失败
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <manifest.json> [--skip-sha256]" >&2
  exit 2
fi

MANIFEST="$1"
shift || true
SKIP_SHA256=0
if [ "${1:-}" = "--skip-sha256" ]; then
  SKIP_SHA256=1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "::error::manifest not found: $MANIFEST" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "::error::jq is required but not installed" >&2
  exit 2
fi

# 提取所有 (sku, platform, url, sha256, size, filename) 元组
# manifest 结构: channels.{channel_name}.{sku}.{platform|.mac[]}.url/sha256/size/filename
ENTRIES_JSON=$(
  jq -r '
    .channels as $channels
    | $channels | to_entries[] as $ch
    | $ch.value | to_entries[] as $sku_entry
    | select($sku_entry.key != "base_url") as $sku
    | $sku_entry.value | to_entries[] as $plat
    | if ($plat.value | type) == "array" then
        $plat.value[] | [$sku_entry.key, $plat.key, .url, .sha256, .size, .filename, $ch.key] | @tsv
      else
        [$sku_entry.key, $plat.key, $plat.value.url, $plat.value.sha256, $plat.value.size, $plat.value.filename, $ch.key] | @tsv
      end
  ' "$MANIFEST"
)

if [ -z "$ENTRIES_JSON" ]; then
  echo "::error::No download entries found in manifest" >&2
  exit 2
fi

ENTRY_COUNT=$(echo "$ENTRIES_JSON" | wc -l | tr -d ' ')
echo "=== Verifying $ENTRY_COUNT download entries from $MANIFEST ==="

FAIL_COUNT=0
PASS_COUNT=0

check_magic() {
  local file="$1"
  local filename="$2"
  local magic
  magic=$(head -c 4 "$file" | xxd -p 2>/dev/null || true)
  case "$filename" in
    *.exe)
      # PE: MZ header (4D5A)
      if [[ "$magic" != 4d5a* ]]; then
        echo "  ::error::Not a valid PE executable (expected MZ header, got ${magic})"
        return 1
      fi
      ;;
    *.dmg)
      # DMG: koly magic (6B6F6C79) at offset 0
      if [[ "$magic" != "6b6f6c79" ]]; then
        echo "  ::error::Not a valid DMG (expected koly magic, got ${magic})"
        return 1
      fi
      ;;
    *.apk)
      # APK: PK zip header (504B0304)
      if [[ "$magic" != "504b0304" ]]; then
        echo "  ::error::Not a valid APK (expected PK header, got ${magic})"
        return 1
      fi
      ;;
    *)
      echo "  ::warning::Unknown file type, skipping magic check: $filename"
      ;;
  esac
  return 0
}

check_sku_confusion() {
  local sku="$1"
  local filename="$2"
  local label
  case "$sku" in
    personal) label="Personal" ;;
    enterprise) label="Enterprise" ;;
    *) return 0 ;;
  esac
  if [[ "$filename" == *"$label"* ]]; then
    return 0
  fi
  # macOS dmg is SKU-neutral (XCAGI-{version}-mac-{arch}.dmg), allow
  if [[ "$filename" == XCAGI-*-mac-*.dmg ]]; then
    return 0
  fi
  echo "  ::error::SKU confusion: sku=$sku but filename does not contain '$label': $filename"
  return 1
}

echo "$ENTRIES_JSON" | while IFS=$'\t' read -r sku platform url sha256 size filename channel; do
  [ -z "$sku" ] && continue
  echo ""
  echo "[$channel] $sku/$platform: $filename"
  echo "  URL: $url"
  echo "  Expected: size=$size sha256=$sha256"

  # 1. HTTP HEAD check
  http_code=$(curl -sIL -o /dev/null -w '%{http_code}' --max-time 30 "$url" || echo "000")
  if [ "$http_code" != "200" ]; then
    echo "  ::error::HTTP $http_code (expected 200)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi
  echo "  OK HTTP 200"

  # 2. Content-Length check (HEAD may not always return it, so tolerate absence)
  content_length=$(curl -sIL --max-time 30 "$url" | grep -i '^content-length:' | tail -1 | tr -d '\r' | awk '{print $2}')
  if [ -n "$content_length" ] && [ "$content_length" != "$size" ]; then
    echo "  ::error::Content-Length mismatch: got $content_length, expected $size"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi
  echo "  OK size=$content_length"

  # 3. SKU confusion check
  if ! check_sku_confusion "$sku" "$filename"; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi
  echo "  OK SKU label matches filename"

  # 4. Download + magic + SHA256 (only if not skipped)
  if [ "$SKIP_SHA256" = "1" ]; then
    echo "  SKIP SHA256 (--skip-sha256)"
    PASS_COUNT=$((PASS_COUNT + 1))
    continue
  fi

  tmp_file=$(mktemp)
  trap 'rm -f "$tmp_file"' EXIT
  if ! curl -sL --max-time 600 -o "$tmp_file" "$url"; then
    echo "  ::error::Download failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    rm -f "$tmp_file"
    continue
  fi

  # 4a. Magic check
  if ! check_magic "$tmp_file" "$filename"; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    rm -f "$tmp_file"
    continue
  fi
  echo "  OK file magic"

  # 4b. SHA256 check
  actual_sha=$(shasum -a 256 "$tmp_file" | awk '{print $1}')
  if [ "$actual_sha" != "$sha256" ]; then
    echo "  ::error::SHA256 mismatch: got $actual_sha, expected $sha256"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    rm -f "$tmp_file"
    continue
  fi
  echo "  OK SHA256=$actual_sha"

  rm -f "$tmp_file"
  PASS_COUNT=$((PASS_COUNT + 1))
done

echo ""
echo "=== Verification summary ==="
echo "PASS: $PASS_COUNT"
echo "FAIL: $FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "::error::$FAIL_COUNT download entries failed verification"
  exit 1
fi

echo "All download entries verified successfully."
exit 0
