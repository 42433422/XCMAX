#!/usr/bin/env bash
set -euo pipefail

dmg="${1:?DMG path required}"
version="${2:?Product version required}"
sha="${3:?Git SHA required}"
test -f "${dmg}"
signature="$(codesign -dv --verbose=4 "${dmg}" 2>&1)"
printf '%s\n' "${signature}"
if [[ "${signature}" == *Signature=adhoc* ]]; then
  echo "::error::DMG is still adhoc-signed" >&2
  exit 1
fi
codesign --verify --verbose=2 "${dmg}"
xcrun stapler validate "${dmg}"
spctl -a -vv -t open --context context:primary-signature "${dmg}"
mount_dir="$(mktemp -d)"
cleanup_mount() {
  hdiutil detach "${mount_dir}" -quiet || true
  rmdir "${mount_dir}" 2>/dev/null || true
}
trap cleanup_mount EXIT
hdiutil attach -nobrowse -readonly -quiet -mountpoint "${mount_dir}" "${dmg}"
app="$(find "${mount_dir}" -maxdepth 2 -name XCAGI.app -print -quit)"
test -n "${app}"
codesign --verify --deep --strict --verbose=2 "${app}"
python3 - "${app}/Contents/Resources/build-info.json" "${version}" "${sha}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    identity = json.load(handle)
assert identity.get("version") == sys.argv[2], "packaged product version mismatch"
assert identity.get("gitSha") == sys.argv[3], "packaged Git SHA mismatch"
print(f"Verified packaged identity: {sys.argv[2]} @ {sys.argv[3]}")
PY
backend="${app}/Contents/Resources/backend/xcagi-backend"
test -x "${backend}"
"${backend}" --verify-frozen-critical-runtime
xcrun stapler validate "${app}"
spctl -a -vv -t exec "${app}"
