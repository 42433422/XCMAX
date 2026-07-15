#!/usr/bin/env bash
# Run on the update server. Restore a verified macOS ZIP updater artifact from
# a GitHub Actions artifact using parallel range requests, then publish metadata last.
set -euo pipefail

required=(
  ARTIFACT_URL_B64
  EXPECTED_ARTIFACT_SIZE
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

if [[ ! "${EXPECTED_ARTIFACT_SIZE}" =~ ^[1-9][0-9]+$ ]]; then
  echo "invalid EXPECTED_ARTIFACT_SIZE" >&2
  exit 2
fi

mkdir -p "${REMOTE_WORK}/parts" "${REMOTE_WORK}/extracted" "${STABLE_DEST}" "${OFFICIAL_DEST}"
artifact_url="$(printf '%s' "${ARTIFACT_URL_B64}" | base64 --decode)"
unset ARTIFACT_URL_B64
download_parts="${DOWNLOAD_PARTS:-16}"
if [[ ! "${download_parts}" =~ ^[1-9][0-9]*$ ]] || [ "${download_parts}" -gt 32 ]; then
  echo "invalid DOWNLOAD_PARTS" >&2
  exit 2
fi
chunk_size="$(( (EXPECTED_ARTIFACT_SIZE + download_parts - 1) / download_parts ))"
pids=()
part_paths=()
part_sizes=()
for ((part_index = 0; part_index < download_parts; part_index++)); do
  range_start="$((part_index * chunk_size))"
  if [ "${range_start}" -ge "${EXPECTED_ARTIFACT_SIZE}" ]; then
    break
  fi
  range_end="$((range_start + chunk_size - 1))"
  if [ "${range_end}" -ge "$((EXPECTED_ARTIFACT_SIZE - 1))" ]; then
    range_end="$((EXPECTED_ARTIFACT_SIZE - 1))"
  fi
  part_path="${REMOTE_WORK}/parts/part-$(printf '%02d' "${part_index}")"
  part_paths+=("${part_path}")
  part_sizes+=("$((range_end - range_start + 1))")
  curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 30 --max-time 5400 \
    --range "${range_start}-${range_end}" \
    "${artifact_url}" -o "${part_path}" &
  pids+=("$!")
done

download_failed=0
for pid in "${pids[@]}"; do
  if ! wait "${pid}"; then
    download_failed=1
  fi
done
if [ "${download_failed}" -ne 0 ]; then
  echo "one or more artifact range downloads failed" >&2
  exit 3
fi
for ((part_index = 0; part_index < ${#part_paths[@]}; part_index++)); do
  actual_part_size="$(stat -c '%s' "${part_paths[part_index]}")"
  if [ "${actual_part_size}" != "${part_sizes[part_index]}" ]; then
    echo "artifact range size mismatch at part ${part_index}" >&2
    exit 3
  fi
done

artifact_path="${REMOTE_WORK}/source-artifact.zip"
for part_path in "${part_paths[@]}"; do
  cat "${part_path}" >> "${artifact_path}"
done
unset artifact_url
if [ "$(stat -c '%s' "${artifact_path}")" != "${EXPECTED_ARTIFACT_SIZE}" ]; then
  echo "reassembled artifact size mismatch" >&2
  exit 3
fi
unzip -q "${artifact_path}" -d "${REMOTE_WORK}/extracted"

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
