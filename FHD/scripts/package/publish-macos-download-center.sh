#!/usr/bin/env bash
# Publish the macOS-only desktop release metadata after its signed artifact and
# stable OTA feed are public. Windows may remain on an explicit interim pointer.

set -euo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo "usage: $0 <version> <release-git-sha> <enterprise-artifact-dir> [android-version]" >&2
  exit 2
fi

version="$1"
release_git_sha="$2"
sku_dir="$3"
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
metadata_source="${script_root}/config/download_release.json"
android_version="${4:-$(jq -er '.android_version' "${metadata_source}")}"
android_git_sha="$(jq -er '.android_git_sha' "${metadata_source}")"

if [ -z "${DESKTOP_SSH_KEY:-}" ]; then
  echo "::error::DESKTOP_SSH_KEY is required to publish download-center metadata." >&2
  exit 1
fi
if ! [[ "${release_git_sha}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error::release git SHA must be a full lowercase SHA-1." >&2
  exit 1
fi
if [ ! -d "${sku_dir}" ]; then
  echo "::error::enterprise artifact directory not found: ${sku_dir}" >&2
  exit 1
fi

latest_mac="${sku_dir}/latest-mac.yml"
dmg="$(find "${sku_dir}" -maxdepth 1 -type f -name '*.dmg' -print -quit)"
test -f "${latest_mac}"
test -n "${dmg}"
grep -Fxq "productVersion: ${version}" "${latest_mac}"
grep -Fxq "buildSha: ${release_git_sha}" "${latest_mac}"
grep -Eq '^signature: ed25519:[A-Za-z0-9+/=]+$' "${latest_mac}"

release_dir="$(dirname "$(dirname "${sku_dir}")")"
release_subdir="$(basename "$(dirname "${sku_dir}")")"
tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

python3 "${script_root}/scripts/package/generate-download-manifest.py" \
  --version "${version}" \
  --release-dir "${release_dir}" \
  --release-subdir "${release_subdir}" \
  --git-sha "${release_git_sha}" \
  --android-version "${android_version}" \
  --android-git-sha "${android_git_sha}" \
  --release-metadata-source "${metadata_source}" \
  --output "${tmpdir}/manifest.json" \
  --download-release-output "${tmpdir}/download-release.json"

jq -e --arg version "${version}" --arg sha "${release_git_sha}" --arg android "${android_version}" '
  .schema == "xcagi.download_release.public/v1"
  and .version_lock == $version
  and .download_version == $version
  and .android_version == $android
  and .git_sha == $sha
  and .release_ready == false
  and .release_history[0].version == $version
  and (.release_history[0].notes | any(contains("太阳鸟")))
' "${tmpdir}/download-release.json" >/dev/null
jq -e '
  .schema == "xcagi.download_manifest/v1"
  and .release_ready == false
  and (.channels.official_download.enterprise.mac | length) > 0
  and (.channels.official_download.enterprise.win // null) == null
' "${tmpdir}/manifest.json" >/dev/null

public_latest="${tmpdir}/public-latest-mac.yml"
curl --http1.1 -fsSL --retry 5 --retry-all-errors --connect-timeout 15 --max-time 120 \
  "https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml?release-sha=${release_git_sha}" \
  -o "${public_latest}"
grep -Fxq "productVersion: ${version}" "${public_latest}"
grep -Fxq "buildSha: ${release_git_sha}" "${public_latest}"
cmp -s "${latest_mac}" "${public_latest}"

dmg_name="$(basename "${dmg}")"
local_size="$(python3 -c 'import os, sys; print(os.path.getsize(sys.argv[1]))' "${dmg}")"
local_sha="$(shasum -a 256 "${dmg}" | awk '{print $1}')"
public_dmg="${tmpdir}/${dmg_name}"
curl --http1.1 -fsSL --retry 5 --retry-all-errors --connect-timeout 15 --max-time 1800 \
  "https://xiu-ci.com/xcagi-v${version}/enterprise/${dmg_name}?release-sha=${release_git_sha}" \
  -o "${public_dmg}"
public_size="$(python3 -c 'import os, sys; print(os.path.getsize(sys.argv[1]))' "${public_dmg}")"
public_sha="$(shasum -a 256 "${public_dmg}" | awk '{print $1}')"
test "${public_size}" = "${local_size}"
test "${public_sha}" = "${local_sha}"

host="${FHD_PUSH_HOST:-119.27.178.147}"
mkdir -p "${HOME}/.ssh"
printf '%s\n' "${DESKTOP_SSH_KEY}" > "${HOME}/.ssh/id_ci"
chmod 600 "${HOME}/.ssh/id_ci"
ssh-keyscan -H "${host}" >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
ssh_opts=(-i "${HOME}/.ssh/id_ci" -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=15)

publish_json_atomically() {
  local source="$1"
  local target="$2"
  local remote_tmp="${target}.tmp.${GITHUB_RUN_ID:-manual}.${GITHUB_RUN_ATTEMPT:-1}"
  ssh "${ssh_opts[@]}" "root@${host}" "mkdir -p '$(dirname "${target}")'"
  scp "${ssh_opts[@]}" "${source}" "root@${host}:${remote_tmp}"
  ssh "${ssh_opts[@]}" "root@${host}" \
    "chmod 0644 '${remote_tmp}' && mv -f '${remote_tmp}' '${target}'"
}

official_root="/var/www/xcagi-v${version}"
ssh "${ssh_opts[@]}" "root@${host}" \
  "chmod a+rx '${official_root}' '${official_root}/enterprise' '/var/www/update/releases/stable/enterprise'"
publish_json_atomically "${tmpdir}/manifest.json" "${official_root}/manifest.json"
publish_json_atomically "${tmpdir}/download-release.json" "${official_root}/download-release.json"

for target in \
  "/root/成都修茈科技有限公司/download-release.json" \
  "/root/成都修茈科技有限公司/MODstore_deploy/market/public/download-release.json" \
  "/root/成都修茈科技有限公司/MODstore_deploy/market/dist/download-release.json" \
  "/root/成都修茈科技有限公司/corp-butler/download-release.json"
do
  publish_json_atomically "${tmpdir}/download-release.json" "${target}"
done

public_pointer="${tmpdir}/public-download-release.json"
for attempt in $(seq 1 12); do
  curl --http1.1 -fsSL --retry 3 --retry-all-errors --connect-timeout 15 --max-time 60 \
    "https://xiu-ci.com/download-release.json?release-run=${GITHUB_RUN_ID:-manual}-${attempt}" \
    -o "${public_pointer}"
  if jq -e --arg version "${version}" --arg sha "${release_git_sha}" --arg android "${android_version}" '
    .schema == "xcagi.download_release.public/v1"
    and .version_lock == $version
    and .download_version == $version
    and .android_version == $android
    and .git_sha == $sha
    and .release_ready == false
    and .release_history[0].version == $version
    and (.release_history[0].notes | any(contains("太阳鸟")))
  ' "${public_pointer}" >/dev/null; then
    break
  fi
  if [ "${attempt}" -eq 12 ]; then
    echo "::error::public download-release.json did not converge." >&2
    jq . "${public_pointer}" || true
    exit 1
  fi
  sleep 5
done

download_html="${tmpdir}/download.html"
release_html="${tmpdir}/download-releases.html"
for attempt in $(seq 1 12); do
  curl --http1.1 -fsSL --connect-timeout 15 --max-time 60 \
    "https://xiu-ci.com/download?release-run=${GITHUB_RUN_ID:-manual}-${attempt}" -o "${download_html}"
  curl --http1.1 -fsSL --connect-timeout 15 --max-time 60 \
    "https://xiu-ci.com/download/releases?release-run=${GITHUB_RUN_ID:-manual}-${attempt}" -o "${release_html}"
  if grep -Fq 'compareVersions(hotfix.version, state.version) >= 0' "${download_html}" && \
     grep -Fq 'compareVersions(hotfix.version, history[0].version) >= 0' "${release_html}"; then
    echo "Download center metadata and changelog verified for ${version} @ ${release_git_sha}."
    exit 0
  fi
  sleep 5
done

echo "::error::download center pages did not expose the same-version Windows interim contract." >&2
exit 1
