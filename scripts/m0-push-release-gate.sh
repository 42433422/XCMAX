#!/usr/bin/env bash
# Push chore/release-gate-m0 to ai-excel-helper and fast-forward master.
# Requires: git push access (HTTPS token or SSH) and network to github.com.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WT="${ROOT}/../.worktrees/release-gate-m0"

if [[ ! -d "$WT/.git" ]]; then
  git -C "$ROOT" fetch origin master
  git -C "$ROOT" worktree add -B chore/release-gate-m0 "$WT" origin/master
  if [[ -d /tmp/fhd-release-gate ]]; then
    echo "Applying prepared commit from /tmp/fhd-release-gate ..."
    git -C "$WT" cherry-pick /tmp/fhd-release-gate 2>/dev/null || {
      echo "Cherry-pick failed; apply patches from $ROOT/patches/ manually"
      exit 1
    }
  fi
fi

cd "$WT"
git push -u origin chore/release-gate-m0
git push origin chore/release-gate-m0:master
echo "Pushed. Trigger CI: https://github.com/42433422/ai-excel-helper/actions/workflows/test.yml"
echo "Then add required check: Release gate (hard block)"
