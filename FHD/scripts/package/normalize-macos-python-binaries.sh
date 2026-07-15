#!/usr/bin/env bash
# Normalize native wheel Mach-O signatures before PyInstaller imports hooks.
set -euo pipefail

PYTHON="${1:-python3}"
if [[ "$(uname -s)" != "Darwin" ]]; then
  exit 0
fi

SITE_PACKAGES="$("${PYTHON}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

if [[ ! -d "${SITE_PACKAGES}" ]]; then
  echo "[err] Python site-packages directory missing: ${SITE_PACKAGES}" >&2
  exit 1
fi

sign_binary() {
  local binary="$1"
  local output
  if ! output="$(codesign --force --sign - "${binary}" 2>&1)"; then
    printf '[err] codesign failed for %s\n%s\n' "${binary}" "${output}" >&2
    return 1
  fi
}

while IFS= read -r -d '' binary; do
  sign_binary "${binary}"
done < <(find "${SITE_PACKAGES}" -type f -name '*.dylib' -print0)

while IFS= read -r -d '' binary; do
  sign_binary "${binary}"
done < <(find "${SITE_PACKAGES}" -type f -name '*.so' -print0)

"${PYTHON}" -c '
import av
import ctranslate2
import gevent

print(
    "macOS native Python runtime OK: "
    f"PyAV {av.__version__}, CTranslate2 {ctranslate2.__version__}, gevent {gevent.__version__}"
)
'
