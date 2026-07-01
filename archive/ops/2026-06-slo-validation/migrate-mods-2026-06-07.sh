#!/usr/bin/env bash
# 将 FHD/mods 全量迁出至 mods-export-2026-06-07/，保留干净通用宿主。
# 用法:
#   bash migrate-mods-2026-06-07.sh --dry-run
#   bash migrate-mods-2026-06-07.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FHD="$ROOT/FHD"
SSOT="$FHD/mods"
XCAGI_MODS="$FHD/XCAGI/mods"
EXPORT="$ROOT/mods-export-2026-06-07"
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "Usage: bash migrate-mods-2026-06-07.sh [--dry-run]"
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$SSOT" ]]; then
  echo "Missing SSOT dir: $SSOT" >&2
  exit 1
fi

mods=()
while IFS= read -r entry; do
  [[ -n "$entry" ]] && mods+=("$entry")
done < <(find "$SSOT" -mindepth 1 -maxdepth 1 ! -name '.DS_Store' -print | sort)

if [[ ${#mods[@]} -eq 0 ]]; then
  echo "Nothing to migrate under $SSOT (already clean?)."
  exit 0
fi

echo "Export target: $EXPORT"
echo "Mod count: ${#mods[@]}"
echo

for src in "${mods[@]}"; do
  name="$(basename "$src")"
  dest="$EXPORT/$name"
  echo "  mv  $src  ->  $dest"
done

if [[ -d "$XCAGI_MODS" ]]; then
  xcagi_count="$(find "$XCAGI_MODS" -mindepth 1 -maxdepth 1 ! -name '.DS_Store' | wc -l | tr -d ' ')"
  if [[ "$xcagi_count" != "0" ]]; then
    echo
    echo "Also clear XCAGI export mirror: $XCAGI_MODS ($xcagi_count entries)"
  fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "[dry-run] No files changed."
  exit 0
fi

mkdir -p "$EXPORT"

for src in "${mods[@]}"; do
  name="$(basename "$src")"
  dest="$EXPORT/$name"
  if [[ -e "$dest" ]]; then
    echo "Skip (already exists): $dest" >&2
    continue
  fi
  mv "$src" "$dest"
done

cat >"$EXPORT/README.md" <<'EOF'
# Mod 导出包 · 2026-06-07

自 `FHD/mods/` 迁出的全部 Mod，供逐个回装/改造。

- **宿主**：`FHD/mods/` 已清空，仅留 README，运行「干净通用版」
- **回装**：将单个 Mod 目录复制回 `FHD/mods/<mod-id>/`，再按需恢复 vite alias 与路由 redirect
- **XCAGI 副本**：`FHD/XCAGI/mods/` 为打包导出路径，回装后执行 `python FHD/scripts/dev/mods_ssot.py sync`
EOF

cat >"$SSOT/README.md" <<'EOF'
# Mod SSOT（干净通用宿主）

全部 Mod 已迁出至仓库根 `mods-export-2026-06-07/`。

开发时按需将单个 Mod 复制回本目录，勿一次性全量回装。
EOF

if [[ -d "$XCAGI_MODS" ]]; then
  if command -v chflags >/dev/null 2>&1; then
    chflags -R nouchg "$XCAGI_MODS" 2>/dev/null || true
  fi
  find "$XCAGI_MODS" -mindepth 1 -maxdepth 1 ! -name 'README.md' -exec rm -rf {} +
  cat >"$XCAGI_MODS/README.md" <<'EOF'
# XCAGI Mod 导出副本（已清空）

SSOT 在 `FHD/mods/`。回装 Mod 后运行:

  python FHD/scripts/dev/mods_ssot.py sync
EOF
fi

echo
echo "Done. Mods exported to: $EXPORT"
echo "Clean host: $SSOT"
