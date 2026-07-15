#!/usr/bin/env bash
# Run on the update server. Restore a verified macOS ZIP updater artifact from
# a short-lived GitHub Actions artifact URL, then publish metadata last.
set -euo pipefail

required=(
  ARTIFACT_URL_B64
  REMOTE_WORK
  ZIP_NAME
  EXPECTED_BUILD_SHA
  EXPECTED_SIZE
  EXPECTED_SHA512
  STABLE_DEST
  OFFICIAL_DEST
)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "missing required environment variable: ${name}" >&2
    exit 2
  fi
done

case "${REMOTE_WORK}" in
  /tmp/xcagi-feed-repair-*) ;;
  *)
    echo "unsafe REMOTE_WORK: ${REMOTE_WORK}" >&2
    exit 2
    ;;
esac
case "${ZIP_NAME}" in
  XCAGI-Enterprise-*-mac-arm64.zip|XCAGI-Enterprise-*-mac-x64.zip) ;;
  *)
    echo "unsafe ZIP_NAME: ${ZIP_NAME}" >&2
    exit 2
    ;;
esac
case "${STABLE_DEST}" in
  /var/www/update/releases/stable/*) ;;
  *)
    echo "unsafe STABLE_DEST: ${STABLE_DEST}" >&2
    exit 2
    ;;
esac
case "${OFFICIAL_DEST}" in
  /var/www/xcagi-v*/enterprise) ;;
  *)
    echo "unsafe OFFICIAL_DEST: ${OFFICIAL_DEST}" >&2
    exit 2
    ;;
esac

cleanup() {
  rm -rf -- "${REMOTE_WORK}"
}
trap cleanup EXIT

mkdir -p "${REMOTE_WORK}/extracted" "${STABLE_DEST}" "${OFFICIAL_DEST}"
artifact_url="$(printf '%s' "${ARTIFACT_URL_B64}" | base64 --decode)"
unset ARTIFACT_URL_B64
curl -fL --retry 3 --retry-delay 2 --max-time 1800 \
  "${artifact_url}" -o "${REMOTE_WORK}/source-artifact.zip"
unset artifact_url
unzip -q "${REMOTE_WORK}/source-artifact.zip" -d "${REMOTE_WORK}/extracted"

mapfile -t zip_matches < <(
  find "${REMOTE_WORK}/extracted" -type f -name "${ZIP_NAME}" -print
)
if [ "${#zip_matches[@]}" -ne 1 ]; then
  echo "expected exactly one ${ZIP_NAME} in downloaded artifact" >&2
  exit 3
fi
zip_path="${zip_matches[0]}"
blockmap_path="${zip_path}.blockmap"
feed_path="${REMOTE_WORK}/latest-mac.yml"
test -f "${blockmap_path}"
test -f "${feed_path}"

actual_build_sha="$(
  python3 "${REMOTE_WORK}/extract_zip_build_sha.py" "${zip_path}"
)"
if [ "${actual_build_sha}" != "${EXPECTED_BUILD_SHA}" ]; then
  echo "downloaded ZIP build identity mismatch" >&2
  exit 4
fi
actual_meta="$(
  python3 "${REMOTE_WORK}/hash_file_sha512.py" "${zip_path}"
)"
actual_size="$(printf '%s\n' "${actual_meta}" | sed -n '1p')"
actual_sha512="$(printf '%s\n' "${actual_meta}" | sed -n '2p')"
if [ "${actual_size}" != "${EXPECTED_SIZE}" ] || [ "${actual_sha512}" != "${EXPECTED_SHA512}" ]; then
  echo "downloaded ZIP hash or size mismatch" >&2
  exit 4
fi

cp -f "${zip_path}" "${OFFICIAL_DEST}/${ZIP_NAME}.part"
cp -f "${blockmap_path}" "${OFFICIAL_DEST}/${ZIP_NAME}.blockmap.part"
cp -f "${feed_path}" "${OFFICIAL_DEST}/latest-mac.yml.part"
cp -f "${OFFICIAL_DEST}/${ZIP_NAME}.part" "${STABLE_DEST}/${ZIP_NAME}.part"
cp -f "${OFFICIAL_DEST}/${ZIP_NAME}.blockmap.part" "${STABLE_DEST}/${ZIP_NAME}.blockmap.part"
cp -f "${OFFICIAL_DEST}/latest-mac.yml.part" "${STABLE_DEST}/latest-mac.yml.part"

cmp -s "${OFFICIAL_DEST}/${ZIP_NAME}.part" "${STABLE_DEST}/${ZIP_NAME}.part"
cmp -s "${OFFICIAL_DEST}/latest-mac.yml.part" "${STABLE_DEST}/latest-mac.yml.part"

mv -f "${OFFICIAL_DEST}/${ZIP_NAME}.part" "${OFFICIAL_DEST}/${ZIP_NAME}"
mv -f "${OFFICIAL_DEST}/${ZIP_NAME}.blockmap.part" "${OFFICIAL_DEST}/${ZIP_NAME}.blockmap"
mv -f "${STABLE_DEST}/${ZIP_NAME}.part" "${STABLE_DEST}/${ZIP_NAME}"
mv -f "${STABLE_DEST}/${ZIP_NAME}.blockmap.part" "${STABLE_DEST}/${ZIP_NAME}.blockmap"
# Feed metadata is the commit point and is always published last.
mv -f "${OFFICIAL_DEST}/latest-mac.yml.part" "${OFFICIAL_DEST}/latest-mac.yml"
mv -f "${STABLE_DEST}/latest-mac.yml.part" "${STABLE_DEST}/latest-mac.yml"

cmp -s "${OFFICIAL_DEST}/latest-mac.yml" "${STABLE_DEST}/latest-mac.yml"
for published_zip in \
  "${OFFICIAL_DEST}/${ZIP_NAME}" \
  "${STABLE_DEST}/${ZIP_NAME}"; do
  published_meta="$(
    python3 "${REMOTE_WORK}/hash_file_sha512.py" "${published_zip}"
  )"
  test "$(printf '%s\n' "${published_meta}" | sed -n '1p')" = "${EXPECTED_SIZE}"
  test "$(printf '%s\n' "${published_meta}" | sed -n '2p')" = "${EXPECTED_SHA512}"
done

echo "restored verified macOS ZIP updater and identical feed metadata"
