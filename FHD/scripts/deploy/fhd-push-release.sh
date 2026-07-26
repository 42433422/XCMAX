#!/usr/bin/env bash
# 本机：打包 FHD API 发布物并原子 scp 到 update 服务器（供 cron 拉取式应用）。
#
# 用法（FHD 根目录或任意目录）:
#   bash scripts/deploy/fhd-push-release.sh
#
# 环境变量:
#   FHD_SKIP_PACK=1              跳过 pack（使用已有 dist/deploy 产物）
#   FHD_PUSH_HOST                默认 119.27.178.147
#   FHD_PUSH_USER                默认 root
#   FHD_RELEASE_CHANNEL          stable（prod）| staging；决定默认远端目录
#   FHD_PUSH_REMOTE_DIR          默认 /var/www/update/releases/<channel>/server
#   FHD_PUSH_SSH_KEY             SSH 私钥路径（默认 ~/.ssh/id_rsa 等）
#   FHD_RELEASE_OUT_DIR          与 pack 脚本一致
#   FHD_PUSH_IMAGE_TAR           auto（仅 image 模式）| 1（强制）| 0（跳过）
#   FHD_PUSH_APPLY_NOW           1 上传后立刻远端应用并验证；strict CI 默认 1
#   FHD_PUSH_REMOTE_DEPLOY_ROOT  默认 /opt/fhd-full
#   FHD_PUSH_HEALTH_URL          远端本机健康地址，默认 http://127.0.0.1:5100/api/health?lite=true
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FHD_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
# shellcheck source=lib/deploy_emit.sh
. "$SCRIPT_DIR/lib/deploy_emit.sh"
# shellcheck source=lib/verify_release_identity.sh
. "$SCRIPT_DIR/lib/verify_release_identity.sh"
export DEPLOY_SCRIPT_ID="fhd_push_release"

OUT_DIR="${FHD_RELEASE_OUT_DIR:-$FHD_ROOT/dist/deploy}"
CHANNEL="${FHD_RELEASE_CHANNEL:-stable}"
case "$CHANNEL" in
  stable | staging) ;;
  *)
    echo "[err] FHD_RELEASE_CHANNEL 须为 stable 或 staging，当前: $CHANNEL" >&2
    exit 1
    ;;
esac
HOST="${FHD_PUSH_HOST:-119.27.178.147}"
USER="${FHD_PUSH_USER:-root}"
REMOTE_DIR="${FHD_PUSH_REMOTE_DIR:-/var/www/update/releases/${CHANNEL}/server}"
SSH_KEY="${FHD_PUSH_SSH_KEY:-}"

SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=120)
SCP_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=120)
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS+=(-i "$SSH_KEY")
  SCP_OPTS+=(-i "$SSH_KEY")
fi

REMOTE="${USER}@${HOST}"
SSH=(ssh "${SSH_OPTS[@]}")
SCP=(scp "${SCP_OPTS[@]}")
RSYNC_SHELL=""
printf -v RSYNC_SHELL '%q ' "${SSH[@]}"

APPLY_NOW="${FHD_PUSH_APPLY_NOW:-}"
if [[ -z "$APPLY_NOW" ]]; then
  case "${FHD_CVM_PUSH_STRICT:-false}" in
    1 | true | TRUE | yes | YES) APPLY_NOW=1 ;;
    *) APPLY_NOW=0 ;;
  esac
fi
case "$APPLY_NOW" in
  0 | 1) ;;
  *)
    echo "[err] FHD_PUSH_APPLY_NOW 须为 0 或 1，当前: $APPLY_NOW" >&2
    exit 1
    ;;
esac

deploy_emit bootstrap started "host=$HOST channel=$CHANNEL remote_dir=$REMOTE_DIR"

if [[ "${FHD_SKIP_PACK:-0}" != "1" ]]; then
  deploy_emit pack started "invoke=fhd-pack-release.sh channel=$CHANNEL"
  FHD_RELEASE_CHANNEL="$CHANNEL" bash "$SCRIPT_DIR/fhd-pack-release.sh"
  deploy_emit pack ok
fi

if [[ -n "${FHD_IMAGE_REF:-}" && -n "${FHD_IMAGE_DIGEST:-}" ]]; then
  deploy_emit merge started "invoke=fhd-merge-manifest-image.sh"
  FHD_MANIFEST_PATH="$OUT_DIR/fhd-manifest.json" \
    bash "$SCRIPT_DIR/fhd-merge-manifest-image.sh"
  deploy_emit merge ok
fi

MANIFEST="$OUT_DIR/fhd-manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "[err] manifest 不存在: $MANIFEST" >&2
  deploy_emit push failed "missing_manifest"
  exit 1
fi

IFS='|' read -r ARTIFACT SHA256 VERSION GIT_SHA DEPLOY_MODE IMAGE IMAGE_DIGEST ADMIN_CONSOLE_SHA256 <<<"$(
  python3 - <<'PY' "$MANIFEST"
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
values = [
    str(doc.get("artifact", "")),
    str(doc.get("sha256", "")),
    str(doc.get("version", "")),
    str(doc.get("git_sha", "")),
    str(doc.get("deploy_mode", "tarball")),
    str(doc.get("image", "")),
    str(doc.get("image_digest", "")),
    str(doc.get("admin_console_sha256", "")),
]
if any("|" in value or "\n" in value for value in values):
    raise SystemExit("manifest contains an invalid field delimiter")
print("|".join(values))
PY
)"

TARBALL="$OUT_DIR/$ARTIFACT"
if [[ -z "$ARTIFACT" || ! -f "$TARBALL" ]]; then
  echo "[err] tarball 不存在: $TARBALL" >&2
  deploy_emit push failed "missing_tarball"
  exit 1
fi

LOCAL_SHA="$(python3 - <<'PY' "$TARBALL"
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

if [[ "$LOCAL_SHA" != "$SHA256" ]]; then
  echo "[err] manifest sha256 与本地 tarball 不符" >&2
  deploy_emit push failed "sha256_mismatch"
  exit 1
fi
[[ "$ADMIN_CONSOLE_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "[err] manifest 缺少管理端不可变资产身份" >&2
  deploy_emit push failed "admin_identity_missing"
  exit 1
}

deploy_emit push started "artifact=$ARTIFACT version=$VERSION sha=$GIT_SHA"

"${SSH[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR'"

atomic_upload() {
  local src="$1"
  local dest="$2"
  local part="${dest}.part"
  local local_sz attempt transfer_mode
  local_sz="$(wc -c < "$src" | tr -d '[:space:]')"
  transfer_mode="scp"
  if command -v rsync >/dev/null 2>&1 && \
      "${SSH[@]}" "$REMOTE" "command -v rsync >/dev/null 2>&1"; then
    transfer_mode="rsync"
  fi
  deploy_emit transfer started "artifact=$(basename "$src") mode=$transfer_mode bytes=$local_sz"
  for attempt in 1 2 3; do
    if [[ "$transfer_mode" == "rsync" ]]; then
      # Preserve the remote .part file across interrupted CI runs.  A rerun of
      # the same immutable artifact resumes from the verified prefix instead
      # of retransmitting it from byte zero over the high-latency CVM link.
      if rsync --archive --partial --append-verify --timeout=180 \
          -e "$RSYNC_SHELL" "$src" "${REMOTE}:${part}"; then
        :
      else
        echo "[warn] rsync attempt $attempt interrupted for $(basename "$src"); partial retained" >&2
        sleep "$attempt"
        continue
      fi
    elif ! "${SCP[@]}" "$src" "${REMOTE}:${part}"; then
      echo "[warn] scp attempt $attempt failed for $(basename "$src")" >&2
      # scp cannot resume safely; remove only its incomplete target before a
      # retry.  rsync partials above are intentionally retained.
      "${SSH[@]}" "$REMOTE" "rm -f '$part'" || true
      sleep "$attempt"
      continue
    fi
    if "${SSH[@]}" "$REMOTE" "test -f '$part' && REMOTE_SZ=\$(wc -c < '$part'); \
      if [ "\$REMOTE_SZ" = '$local_sz' ]; then mv -f '$part' '$dest'; echo OK_MOVED; \
      else echo SIZE_MISMATCH "\$REMOTE_SZ" vs '$local_sz'; rm -f '$part'; exit 1; fi"; then
      return 0
    fi
    echo "[warn] verify attempt $attempt failed for $(basename "$src")" >&2
    sleep "$attempt"
  done
  echo "[err] atomic_upload failed after 3 attempts: $(basename "$src")" >&2
  return 1
}

atomic_upload "$TARBALL" "${REMOTE_DIR}/${ARTIFACT}"
atomic_upload "$MANIFEST" "${REMOTE_DIR}/fhd-manifest.json"

IMAGE_TAR="$OUT_DIR/fhd-api-image.tar.gz"
PUSH_IMAGE_TAR="${FHD_PUSH_IMAGE_TAR:-auto}"
case "$PUSH_IMAGE_TAR" in
  auto)
    if [[ "${DEPLOY_MODE:-tarball}" == "image" ]]; then
      PUSH_IMAGE_TAR=1
    else
      PUSH_IMAGE_TAR=0
    fi
    ;;
  0 | 1) ;;
  *)
    echo "[err] FHD_PUSH_IMAGE_TAR 须为 auto、0 或 1，当前: $PUSH_IMAGE_TAR" >&2
    deploy_emit push failed "invalid_push_image_tar"
    exit 1
    ;;
esac

if [[ -f "$IMAGE_TAR" && "$PUSH_IMAGE_TAR" == "1" ]]; then
  deploy_emit push started "artifact=fhd-api-image.tar.gz"
  atomic_upload "$IMAGE_TAR" "${REMOTE_DIR}/fhd-api-image.tar.gz"
  echo "[ok] image_tar=fhd-api-image.tar.gz"
elif [[ -f "$IMAGE_TAR" ]]; then
  deploy_emit push skipped "artifact=fhd-api-image.tar.gz reason=optional"
  echo "[notice] 跳过可选镜像归档；设置 FHD_PUSH_IMAGE_TAR=1 可显式上传"
fi

if [[ "$APPLY_NOW" == "1" ]]; then
  REMOTE_DEPLOY_ROOT="${FHD_PUSH_REMOTE_DEPLOY_ROOT:-/opt/fhd-full}"
  REMOTE_HEALTH_URL="${FHD_PUSH_HEALTH_URL:-http://127.0.0.1:5100/api/health?lite=true}"
  REMOTE_MANIFEST="${REMOTE_DIR}/fhd-manifest.json"
  REMOTE_TARBALL="${REMOTE_DIR}/${ARTIFACT}"
  printf -v APPLY_COMMAND \
    'set -euo pipefail; BOOTSTRAP=$(mktemp -d /tmp/fhd-release-bootstrap.XXXXXX); trap '\''rm -rf -- "$BOOTSTRAP"'\'' EXIT; tar -xzf %q -C "$BOOTSTRAP" ./scripts/deploy; test -x "$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"; FHD_MANIFEST_PATH=%q FHD_ARTIFACT_DIR=%q FHD_DEPLOY_ROOT=%q bash "$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"' \
    "$REMOTE_TARBALL" "$REMOTE_MANIFEST" "$REMOTE_DIR" "$REMOTE_DEPLOY_ROOT"

  deploy_emit apply started "host=$HOST git_sha=$GIT_SHA mode=${DEPLOY_MODE:-tarball}"
  if ! "${SSH[@]}" "$REMOTE" "$APPLY_COMMAND"; then
    deploy_emit apply failed "remote_auto_update_failed"
    echo "[err] 远端自动应用失败；发布未通过" >&2
    exit 1
  fi

  deploy_emit verify started "url=$REMOTE_HEALTH_URL git_sha=$GIT_SHA"
  printf -v HEALTH_COMMAND 'curl --noproxy "*" -fsS --max-time 10 %q' "$REMOTE_HEALTH_URL"
  if ! REMOTE_HEALTH_PAYLOAD="$("${SSH[@]}" "$REMOTE" "$HEALTH_COMMAND")"; then
    deploy_emit verify failed "remote_health_unreachable"
    echo "[err] 远端健康检查不可达；发布未通过" >&2
    exit 1
  fi
  EXPECTED_RUNTIME_IMAGE_DIGEST=""
  if [[ "${DEPLOY_MODE:-tarball}" == "image" ]]; then
    EXPECTED_RUNTIME_IMAGE_DIGEST="${IMAGE_DIGEST:-}"
  fi
  if ! verify_release_identity_payload \
      "$REMOTE_HEALTH_PAYLOAD" \
      "$GIT_SHA" \
      "$EXPECTED_RUNTIME_IMAGE_DIGEST" \
      "$SHA256" \
      "$ADMIN_CONSOLE_SHA256"; then
    deploy_emit verify failed "remote_identity_mismatch"
    echo "[err] 远端运行版本与本次发布身份不一致；发布未通过" >&2
    exit 1
  fi
  deploy_emit verify ok "git_sha=$GIT_SHA"
  deploy_emit apply ok "host=$HOST git_sha=$GIT_SHA"

  # Cleanup is intentionally post-verify: failed or unverified releases retain
  # every rollback artifact. Once the exact SHA is live, bound old immutable
  # tarballs, abandoned partial uploads, and full-tree rollback snapshots.
  REMOTE_PRUNER="${REMOTE_DEPLOY_ROOT}/scripts/deploy/prune_release_cache.py"
  if ! "${SSH[@]}" "$REMOTE" \
      "python3 '$REMOTE_PRUNER' --release-dir '$REMOTE_DIR' --backup-dir '/opt/fhd-full-backups' --current-artifact '$ARTIFACT' --retain-releases 8 --retain-backups 5 --part-max-age-hours 24"; then
    echo "[warn] release cache cleanup failed after verified deploy; runtime remains healthy" >&2
  fi
fi

deploy_emit push ok "channel=$CHANNEL version=$VERSION git_sha=$GIT_SHA mode=${DEPLOY_MODE:-tarball}"
echo "[ok] 已发布至 ${HOST}:${REMOTE_DIR}/ (channel=$CHANNEL)"
echo "[ok] artifact=$ARTIFACT sha256=${SHA256:0:16}... deploy_mode=${DEPLOY_MODE:-tarball}"
if [[ -n "${IMAGE:-}" && -n "${IMAGE_DIGEST:-}" ]]; then
  echo "[ok] image=$IMAGE digest=${IMAGE_DIGEST:0:19}..."
fi
if [[ "$APPLY_NOW" == "1" ]]; then
  echo "[ok] 远端已应用并通过 exact-SHA 健康验证 git_sha=$GIT_SHA"
else
  echo "[hint] 服务器 cron 将在 5 分钟内自动应用；或设置 FHD_PUSH_APPLY_NOW=1 立即应用并验证"
fi
