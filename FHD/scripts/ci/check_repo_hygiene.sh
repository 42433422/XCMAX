#!/usr/bin/env bash
# Shared by Smoke Tests and the frontend-smoke compatibility gate.
set -euo pipefail
tracked_files="$(git ls-files)"
bad=""
while IFS= read -r f; do
  [ -z "${f}" ] && continue
  f="${f#\"}"
  f="${f%\"}"
  [[ "${f}" =~ \.example$ ]] && continue
  [[ "${f}" =~ /\.env\.generic$ ]] && continue
  [[ "${f}" =~ /\.env\.minimal$ ]] && continue
  if [[ "${f}" =~ (^|/)\.env(\.|$) ]] || \
     [[ "${f}" =~ (^|/)secret\.yaml$ ]] || \
     [[ "${f}" =~ login_out\.json$ ]] || \
     [[ "${f}" =~ \.der$ ]] || \
     [[ "${f}" =~ /\.nm- ]] || \
     [[ "${f}" =~ /node_modules/ ]] || \
     [[ "${f}" =~ /__pycache__/ ]] || \
     [[ "${f}" =~ /chroma/ ]] || \
     [[ "${f}" =~ /chroma_db/ ]] || \
     [[ "${f}" =~ /vector_data/.*\.sqlite ]]; then
    bad+="${f}"$'\n'
  fi
done <<< "$tracked_files"
if [ -n "${bad}" ]; then
  echo "Tracked paths that must stay gitignored:"
  printf '%s' "${bad}"
  exit 1
fi
echo "Repo hygiene check passed."
