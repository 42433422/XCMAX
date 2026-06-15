#!/usr/bin/env bash
# Run on the deploy server by deploy-to-server.ps1.
# - Extracts /tmp/vibe_coding_sync.tgz under ${REMOTE_BASE} (full directory replace,
#   so a stale tree never lingers).
# - Creates / reuses a venv inside vibe-coding/.venv.
# - Installs vibe-coding (and optionally eskill-prototype) in editable mode.
# - Runs pytest as a smoke check unless SKIP_TESTS=1.
#
# Inputs (env):
#   REMOTE_BASE_B64  base64 of the parent directory (matches sync-modstore convention)
#   INCLUDE_ESKILL=1 also extract+install eskill-prototype/
#   SKIP_TESTS=1     skip pytest
set -euo pipefail

if [ -z "${REMOTE_BASE_B64:-}" ]; then
  echo "[err] REMOTE_BASE_B64 not set" >&2
  exit 2
fi
REMOTE_BASE="$(printf '%s' "$REMOTE_BASE_B64" | base64 -d)"
TAR="/tmp/vibe_coding_sync.tgz"
test -f "$TAR" || { echo "[err] missing $TAR" >&2; exit 1; }
test -d "$REMOTE_BASE" || { echo "[err] not a dir: $REMOTE_BASE" >&2; exit 1; }

cd "$REMOTE_BASE"

# Quick safety check: tarball top dirs match what we expect
TOP="$(tar -tzf "$TAR" 2>/dev/null | awk -F/ 'NF>1{print $1}' | sort -u)"
echo "[ok] tarball top entries:"; printf '  %s\n' $TOP
echo "$TOP" | grep -q '^vibe-coding$' || { echo "[err] tarball missing vibe-coding/" >&2; exit 1; }
if [ "${INCLUDE_ESKILL:-0}" = "1" ]; then
  echo "$TOP" | grep -q '^eskill-prototype$' || {
    echo "[err] INCLUDE_ESKILL=1 but tarball missing eskill-prototype/" >&2; exit 1; }
fi

# Replace whole vibe-coding/ — the directory is generated, no in-place state worth keeping
[ -d vibe-coding ] && { echo "[ok] removing old vibe-coding/"; rm -rf vibe-coding; }
if [ "${INCLUDE_ESKILL:-0}" = "1" ] && [ -d eskill-prototype ]; then
  echo "[ok] removing old eskill-prototype/"
  rm -rf eskill-prototype
fi

echo "[ok] extracting to $REMOTE_BASE"
tar xzf "$TAR"
rm -f "$TAR"

# Create / reuse a dedicated venv inside vibe-coding/
cd "$REMOTE_BASE/vibe-coding"
if ! command -v python3 >/dev/null 2>&1; then
  echo "[err] python3 not found on server" >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "[ok] creating .venv (python3 $(python3 --version 2>&1))"
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q -U pip

echo "[ok] pip install -e vibe-coding[test]"
pip install -q -e ".[test]"

if [ "${INCLUDE_ESKILL:-0}" = "1" ]; then
  echo "[ok] pip install -e eskill-prototype[test]"
  cd "$REMOTE_BASE/eskill-prototype"
  pip install -q -e ".[test]"
fi

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  cd "$REMOTE_BASE/vibe-coding"
  echo "[ok] pytest standalone vibe-coding..."
  if ! python -m pytest tests -q --tb=short; then
    echo "[err] standalone tests failed" >&2; exit 1
  fi

  echo "[ok] running standalone workflow example..."
  python examples/03_workflow.py

  if [ "${INCLUDE_ESKILL:-0}" = "1" ]; then
    cd "$REMOTE_BASE/eskill-prototype"
    echo "[ok] pytest eskill vibe_coding subset..."
    if ! python -m pytest tests -k vibe_coding -q --tb=short; then
      echo "[err] eskill vibe_coding tests failed" >&2; exit 1
    fi
  fi
fi

cat <<EOF

[ok] vibe-coding installed at: $REMOTE_BASE/vibe-coding
[ok] activate venv:   source $REMOTE_BASE/vibe-coding/.venv/bin/activate
[ok] try CLI:         python -m vibe_coding --mock code "make a demo skill"
EOF
if [ "${INCLUDE_ESKILL:-0}" = "1" ]; then
  echo "[ok] eskill-prototype installed at: $REMOTE_BASE/eskill-prototype"
fi
echo "[ok] deploy done."
