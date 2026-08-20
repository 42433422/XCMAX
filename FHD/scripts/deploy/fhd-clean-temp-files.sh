#!/usr/bin/env bash
# 定期清理 CVM 上残留的传输临时文件：
#   - rsync 中断残留的 .~tmp~（--partial/--delay-updates 留在目标端的临时文件）
#   - 上传/下载分片 .part（atomic_upload / 恢复脚本的暂存分片）
#   - rsync --partial-dir 残留的 .partial 目录
# 仅删除超过年龄阈值的条目；进行中的传输（mtime 持续更新）不会被误删。
#
# 用法（CVM 上执行）:
#   bash /opt/fhd-full/scripts/deploy/fhd-clean-temp-files.sh
#
# 环境变量:
#   FHD_TMP_CLEAN_ROOTS      扫描根目录（空格分隔），默认 "/var/www /opt/fhd-full-backups"
#   FHD_TMP_MIN_AGE_MIN      .~tmp~ 最小年龄（分钟），默认 60
#   FHD_TMP_PART_AGE_MIN     .part/.partial 最小年龄（分钟），默认 1440（24h）
#   FHD_TMP_DRY_RUN          1 = 只列出不删除（排查用）
#   FHD_TMP_CLEAN_LOG        日志路径，默认 /var/log/fhd-temp-cleanup.log
set -euo pipefail

ROOTS="${FHD_TMP_CLEAN_ROOTS:-/var/www /opt/fhd-full-backups}"
TMP_AGE_MIN="${FHD_TMP_MIN_AGE_MIN:-60}"
PART_AGE_MIN="${FHD_TMP_PART_AGE_MIN:-1440}"
DRY_RUN="${FHD_TMP_DRY_RUN:-0}"
LOG="${FHD_TMP_CLEAN_LOG:-/var/log/fhd-temp-cleanup.log}"

[[ "$TMP_AGE_MIN" =~ ^[0-9]+$ ]] || { echo "[err] FHD_TMP_MIN_AGE_MIN 非法: $TMP_AGE_MIN" >&2; exit 1; }
[[ "$PART_AGE_MIN" =~ ^[0-9]+$ ]] || { echo "[err] FHD_TMP_PART_AGE_MIN 非法: $PART_AGE_MIN" >&2; exit 1; }

# 只允许扫描已知发布/备份目录，防止误删其他路径
safe_roots=()
for root in $ROOTS; do
  case "$root" in
    /var/www*) safe_roots+=("$root") ;;
    /opt/fhd-full*) safe_roots+=("$root") ;;
    *) echo "[err] 拒绝扫描非发布目录: $root" >&2; exit 1 ;;
  esac
done

deleted=0
_rm() {
  local target="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] rm -rf -- '$target'"
  else
    rm -rf -- "$target"
  fi
  deleted=$((deleted + 1))
}

for root in "${safe_roots[@]}"; do
  [[ -d "$root" ]] || continue
  # rsync 中断残留的临时文件（.~tmp~）
  while IFS= read -r -d '' f; do
    _rm "$f"
  done < <(find "$root" -type f -name '*.~tmp~' -mmin "+$TMP_AGE_MIN" -print0 2>/dev/null)
  # 上传/下载分片文件（.part）
  while IFS= read -r -d '' f; do
    _rm "$f"
  done < <(find "$root" -type f -name '*.part' -mmin "+$PART_AGE_MIN" -print0 2>/dev/null)
  # rsync --partial-dir 残留目录（.partial）
  while IFS= read -r -d '' d; do
    _rm "$d"
  done < <(find "$root" -type d -name '*.partial' -mmin "+$PART_AGE_MIN" -print0 2>/dev/null)
done

TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "$TS cleaned=$deleted roots='${safe_roots[*]}' tmp_age=${TMP_AGE_MIN}m part_age=${PART_AGE_MIN}m" >> "$LOG"
echo "[ok] $TS 已清理 $deleted 个临时文件"
