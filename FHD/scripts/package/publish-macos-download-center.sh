#!/usr/bin/env bash
# Frozen Mac pair verification is offline by default. Publish only after owner authorization.
set -euo pipefail
if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
  echo 'usage: publish-macos-download-center.sh <version> <sha> <pair-dir> [--dry-run|--publish]' >&2; exit 2
fi
version="$1"; release_git_sha="$2"; sku_dir="$3"; mode="${4:---dry-run}"
case "$mode" in --dry-run|--publish) ;; *) exit 2 ;; esac
[[ "$release_git_sha" =~ ^[0-9a-f]{40}$ && "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
metadata_source="$script_root/config/download_release.json"
latest_mac="$sku_dir/latest-mac.yml"
if [ "$mode" = --publish ]; then
  test -n "${XCAGI_UPDATE_ED25519_PUBLIC_KEY:-}"
  trusted="$(cd "$script_root" && python3 -c 'from scripts.release.prepare_mac_candidate_pair import desktop_public_key; print(desktop_public_key())')"
  test "$XCAGI_UPDATE_ED25519_PUBLIC_KEY" = "$trusted"
fi
# Recompute every staged digest. A first-DMG match cannot certify the other architecture.
python3 - "$sku_dir" "$version" "$release_git_sha" <<'PY'
import base64, hashlib, json, os, pathlib, sys
import yaml
from cryptography.hazmat.primitives import serialization
p=pathlib.Path(sys.argv[1]);version,sha=sys.argv[2:];review=json.loads((p/'pair-review.json').read_text())
assert review['source_sha']==sha and review['version']==version
rows=review['architectures'];assert [r['architecture'] for r in rows]==['arm64','x64']
for row in rows:
    names={v['name'] for v in row['files']}
    stem=f'XCAGI-Enterprise-{version}-mac-{row["architecture"]}'
    assert names=={stem+'.zip',stem+'.dmg',stem+'.zip.blockmap'}
    for item in row['files']:
        path=p/item['name'];assert path.stat().st_size==item['size']
        with path.open('rb') as f: assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
text=(p/'latest-mac.yml').read_text();lines=text.splitlines();signatures=[s for s in lines if s.startswith('signature: ed25519:')];assert len(signatures)==1
body='\n'.join(s for s in lines if not s.startswith('signature:')).rstrip()
public=os.environ.get('XCAGI_UPDATE_ED25519_PUBLIC_KEY','')
if public:
    key=serialization.load_pem_public_key(public.replace('\\n','\n').encode())
else:
    key=serialization.load_pem_private_key(os.environ['XCAGI_UPDATE_ED25519_PRIVATE_KEY'].replace('\\n','\n').encode(),password=None).public_key()
key.verify(base64.b64decode(signatures[0].split('ed25519:',1)[1],validate=True),body.encode())
feed=yaml.safe_load(body);assert feed['buildSha']==sha and feed['productVersion']==version
assert len(feed['files'])==2
prefix=f'https://xiu-ci.com/xcagi-v{version}/builds/{sha}/enterprise/'
for arch in ('arm64','x64'):
    path=p/f'XCAGI-Enterprise-{version}-mac-{arch}.zip';rows=[r for r in feed['files'] if r['url']==prefix+path.name];assert len(rows)==1
    with path.open('rb') as f: assert rows[0]['sha512']==base64.b64encode(hashlib.file_digest(f,'sha512').digest()).decode()
    assert rows[0]['size']==path.stat().st_size
print('Verified frozen ARM/x64 original bytes and fresh combined signature; customer acceptance remains external.')
PY
tmpdir="$(mktemp -d)"; trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$tmpdir/release/xcagi-v$version"
ln -s "$(cd "$sku_dir" && pwd)" "$tmpdir/release/xcagi-v$version/enterprise"
immutable_base="https://xiu-ci.com/xcagi-v$version/builds/$release_git_sha"
python3 "$script_root/scripts/package/generate-download-manifest.py" \
  --version "$version" --release-dir "$tmpdir/release" --release-subdir "xcagi-v$version" \
  --git-sha "$release_git_sha" --android-version "$(jq -er .android_version "$metadata_source")" \
  --android-git-sha "$(jq -er .android_git_sha "$metadata_source")" --release-metadata-source "$metadata_source" \
  --auto-update-base "$immutable_base" --official-download-base "$immutable_base" \
  --output "$tmpdir/manifest.json" --download-release-output "$tmpdir/download-release.json"
# A trusted current global snapshot is mandatory; never derive other platforms from the Mac-only directory.
if [ "$mode" = --dry-run ] && [ -n "${XCAGI_PUBLIC_DOWNLOAD_SNAPSHOT_DIR:-}" ]; then
  cp "$XCAGI_PUBLIC_DOWNLOAD_SNAPSHOT_DIR/download-release.json" "$tmpdir/current-pointer.json"
  cp "$XCAGI_PUBLIC_DOWNLOAD_SNAPSHOT_DIR/manifest.json" "$tmpdir/current-manifest.json"
else
  curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 'https://xiu-ci.com/download-release.json' -o "$tmpdir/current-pointer.json"
  manifest_url="$(python3 - "$tmpdir/current-pointer.json" <<'PYMETA'
import json, sys, urllib.parse
url=json.load(open(sys.argv[1]))['manifest_url'];p=urllib.parse.urlsplit(url)
assert p.scheme=='https' and p.hostname=='xiu-ci.com' and not p.username and p.port in (None,443)
print(url)
PYMETA
)"
  curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 "$manifest_url" -o "$tmpdir/current-manifest.json"
fi
(cd "$script_root" && python3 - "$tmpdir" "$sku_dir/pair-review.json" <<'PYMETA'
import json, pathlib, sys
from scripts.release.prepare_mac_candidate_pair import merge_download_metadata
p=pathlib.Path(sys.argv[1]);load=lambda name:json.loads((p/name).read_text())
public,manifest=merge_download_metadata(load('current-pointer.json'),load('current-manifest.json'),load('download-release.json'),load('manifest.json'),json.load(open(sys.argv[2])))
for name,data in [('download-release.json',public),('manifest.json',manifest)]:
    (p/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
PYMETA
)
jq -e '.release_ready == false and (.channels.official_download.enterprise.mac | length) == 2' "$tmpdir/manifest.json" >/dev/null
if [ "$mode" = --dry-run ]; then
  echo 'Verification complete; public metadata may have been read; no network writes, no release_ready change, no customer delivery PASS.'; exit 0
fi
test "${XCAGI_MAC_PUBLICATION_AUTHORIZED_SHA:-}" = "$release_git_sha"
test -n "${DESKTOP_SSH_KEY:-}"
host="${FHD_PUSH_HOST:-119.27.178.147}"
ssh_dir="$tmpdir/ssh"; mkdir "$ssh_dir"; printf '%s\n' "$DESKTOP_SSH_KEY" > "$ssh_dir/id"; chmod 600 "$ssh_dir/id"
ssh-keyscan -H "$host" > "$ssh_dir/known_hosts"
ssh_opts=(-i "$ssh_dir/id" -o "UserKnownHostsFile=$ssh_dir/known_hosts" -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=15)
remote_root="/var/www/xcagi-v$version/builds/$release_git_sha"
remote_payload="$remote_root/enterprise"
ssh "${ssh_opts[@]}" "root@$host" "mkdir -p '$remote_payload' && chmod 0755 '$remote_root' '$remote_payload'"
# The immutable SHA directory receives all original payloads before any public pointer changes.
rsync -av --partial --delay-updates --include='*.dmg' --include='*.zip' --include='*.zip.blockmap' --exclude='*' \
  -e "ssh ${ssh_opts[*]}" "$sku_dir/" "root@$host:$remote_payload/"
for file in "$sku_dir"/*.dmg "$sku_dir"/*.zip "$sku_dir"/*.zip.blockmap; do
  name="$(basename "$file")"; expected="$(shasum -a 256 "$file" | awk '{print $1}')"
  actual="$(ssh "${ssh_opts[@]}" "root@$host" "sha256sum '$remote_payload/$name' | cut -d ' ' -f1")"; test "$actual" = "$expected"
  public_sha="$(curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 5400 "$immutable_base/enterprise/$name" | shasum -a 256 | awk '{print $1}')"
  test "$public_sha" = "$expected"
  size="$(wc -c < "$file" | tr -d ' ')"
  public_size="$(curl --http1.1 -fsSI --retry 3 --connect-timeout 15 --max-time 120 "$immutable_base/enterprise/$name" | awk 'tolower($1)=="content-length:" {gsub("\r","",$2); n=$2} END {print n}')"; test "$public_size" = "$size"
done
publish_json_atomically() {
  local source="$1" target="$2" remote_tmp="${2}.tmp.${GITHUB_RUN_ID:-manual}.${GITHUB_RUN_ATTEMPT:-1}"
  ssh "${ssh_opts[@]}" "root@$host" "mkdir -p '$(dirname "$target")'"
  scp "${ssh_opts[@]}" "$source" "root@$host:$remote_tmp"
  ssh "${ssh_opts[@]}" "root@$host" "chmod 0644 '$remote_tmp' && mv -f '$remote_tmp' '$target'"
}
curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 'https://xiu-ci.com/download-release.json' -o "$tmpdir/latest-pointer.json"
cmp "$tmpdir/current-pointer.json" "$tmpdir/latest-pointer.json"
manifest_url="$(jq -er .manifest_url "$tmpdir/current-pointer.json")"
curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 "$manifest_url" -o "$tmpdir/latest-manifest.json"
cmp "$tmpdir/current-manifest.json" "$tmpdir/latest-manifest.json"
for root in "$remote_root" "/var/www/xcagi-v$version"; do
  publish_json_atomically "$tmpdir/manifest.json" "$root/manifest.json"
  publish_json_atomically "$tmpdir/download-release.json" "$root/download-release.json"
done
# Both feeds reference immutable verified payloads, so a reader of either old or new feed stays consistent.
for root in "$remote_payload" "/var/www/xcagi-v$version/enterprise" "/var/www/update/releases/stable/enterprise"; do
  publish_json_atomically "$latest_mac" "$root/latest-mac.yml"
done
for target in \
  '/root/成都修茈科技有限公司/download-release.json' \
  '/root/成都修茈科技有限公司/MODstore_deploy/market/public/download-release.json' \
  '/root/成都修茈科技有限公司/MODstore_deploy/market/dist/download-release.json' \
  '/root/成都修茈科技有限公司/corp-butler/download-release.json'; do
  publish_json_atomically "$tmpdir/download-release.json" "$target"
done
for route in "$immutable_base/enterprise/latest-mac.yml" "https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml" "https://xiu-ci.com/xcagi-v$version/enterprise/latest-mac.yml"; do
  curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 "$route?sha=$release_git_sha" -o "$tmpdir/public-feed"; cmp "$latest_mac" "$tmpdir/public-feed"
done
curl --http1.1 -fsSL --retry 3 --connect-timeout 15 --max-time 120 "https://xiu-ci.com/download-release.json?sha=$release_git_sha" -o "$tmpdir/public-pointer"
cmp "$tmpdir/download-release.json" "$tmpdir/public-pointer"
echo 'Frozen ARM/x64 pair and public pointers read back; release_ready remains false.'
