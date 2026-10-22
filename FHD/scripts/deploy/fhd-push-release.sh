#!/usr/bin/env bash
set -euo pipefail
case "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" in 0|1) ;; *) echo "XCMAX_PRESERVE_RELEASE_HISTORY must be 0 or 1" >&2; exit 64 ;; esac

# 打包并原子上传；部署通道与服务器配置见 docs/CI_SSOT.md。
# FHD_PUSH_APPLY_NOW=1 上传后应用并校验 exact SHA；默认由服务器 cron 应用。
# XCMAX_PRESERVE_RELEASE_HISTORY=1 本次保留全部历史，须同时立即应用。
# FHD_PUSH_IMAGE_TAR=auto 仅 image 模式上传镜像，1 强制、0 跳过。

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

if [[ "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" == 1 && "$APPLY_NOW" != 1 ]]; then
  echo "[err] preserving release history requires FHD_PUSH_APPLY_NOW=1" >&2
  exit 64
fi

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
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
  echo "[err] manifest version 无效: $VERSION" >&2
  deploy_emit push failed "invalid_version"
  exit 1
}
[[ "$GIT_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "[err] manifest git_sha 必须是完整 40 位小写 SHA" >&2
  deploy_emit push failed "invalid_git_sha"
  exit 1
}
[[ "$ARTIFACT" =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "[err] manifest artifact 文件名无效" >&2
  deploy_emit push failed "invalid_artifact_name"
  exit 1
}
[[ "$REMOTE_DIR" == /* && "$REMOTE_DIR" != *$'\n'* ]] || {
  echo "[err] FHD_PUSH_REMOTE_DIR 必须是绝对路径" >&2
  deploy_emit push failed "invalid_remote_dir"
  exit 1
}

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

IMMUTABLE_REMOTE_DIR="${FHD_IMMUTABLE_REMOTE_DIR:-/var/www/update/releases/builds/${VERSION}/${GIT_SHA}/server}"
[[ "$IMMUTABLE_REMOTE_DIR" == /* && "$IMMUTABLE_REMOTE_DIR" != *$'\n'* ]] || {
  echo "[err] FHD_IMMUTABLE_REMOTE_DIR 必须是绝对路径" >&2
  deploy_emit push failed "invalid_immutable_remote_dir"
  exit 1
}

deploy_emit push started "artifact=$ARTIFACT version=$VERSION sha=$GIT_SHA immutable_dir=$IMMUTABLE_REMOTE_DIR"

"${SSH[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR' '$IMMUTABLE_REMOTE_DIR'"

atomic_upload() {
  local src="$1"
  local dest="$2"
  local part="${dest}.part"
  local local_sz attempt transfer_mode rsync_resume_flag
  local_sz="$(wc -c < "$src" | tr -d '[:space:]')"
  transfer_mode="scp"
  rsync_resume_flag="--append"
  if command -v rsync >/dev/null 2>&1 && \
      "${SSH[@]}" "$REMOTE" "command -v rsync >/dev/null 2>&1"; then
    transfer_mode="rsync"
    if rsync --help 2>&1 | grep -q -- '--append-verify'; then
      rsync_resume_flag="--append-verify"
    fi
  fi
  deploy_emit transfer started "artifact=$(basename "$src") mode=$transfer_mode bytes=$local_sz"
  for attempt in 1 2 3; do
    if [[ "$transfer_mode" == "rsync" ]]; then
      # Preserve the remote .part file across interrupted CI runs.  A rerun of
      # the same immutable artifact resumes from the verified prefix instead
      # of retransmitting it from byte zero over the high-latency CVM link.
      if rsync --archive --partial "$rsync_resume_flag" --timeout=180 \
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

atomic_upload "$TARBALL" "${IMMUTABLE_REMOTE_DIR}/${ARTIFACT}"

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
  atomic_upload "$IMAGE_TAR" "${IMMUTABLE_REMOTE_DIR}/fhd-api-image.tar.gz"
  echo "[ok] image_tar=fhd-api-image.tar.gz"
elif [[ -f "$IMAGE_TAR" ]]; then
  deploy_emit push skipped "artifact=fhd-api-image.tar.gz reason=optional"
  echo "[notice] 跳过可选镜像归档；设置 FHD_PUSH_IMAGE_TAR=1 可显式上传"
fi

# The version/SHA directory is immutable evidence. Only after every payload is
# present do we atomically promote the channel manifest; the previous SHA stays
# available for an exact rollback without rebuilding.
atomic_upload "$MANIFEST" "${IMMUTABLE_REMOTE_DIR}/fhd-manifest.json"
# Bind controller bytes to the same already-integrated source SHA, never the dirty checkout.
CONTROLLER_HASHES_B64="e30="
if [[ "$CHANNEL" == "stable" ]]; then
CONTROLLER_HASHES_B64="$(python3 - "$FHD_ROOT" "$GIT_SHA" <<'PY_CONTROLLERS'
import base64, hashlib, json, subprocess, sys
root, sha = sys.argv[1:]
subprocess.run(["git", "-C", root, "merge-base", "--is-ancestor", sha, "origin/main"], check=True)
names = ["fhd-auto-update.sh", "fhd-apply-release.sh", "fhd-apply-release-compose.sh",
         "fhd-load-release-image.sh", "lib/deploy_emit.sh", "lib/autonomy_gate.sh",
         "lib/verify_release_identity.sh", "lib/dora_event.sh", "lib/version.sh",
         "lib/verify_admin_console.py", "lib/mod_tree_guard.py", "lib/verify_release_archive.py",
         "lib/service_quiescence.sh", "lib/apply_recovery.sh", "prune_release_cache.py"]
hashes = {name: hashlib.sha256(subprocess.check_output(
    ["git", "-C", root, "show", f"{sha}:FHD/scripts/deploy/{name}"])).hexdigest() for name in names}
print(base64.b64encode(json.dumps(hashes, sort_keys=True).encode()).decode())
PY_CONTROLLERS
)"
fi
"${SSH[@]}" "$REMOTE" "bash -s" -- \
  "$IMMUTABLE_REMOTE_DIR" "$REMOTE_DIR" "$ARTIFACT" "$PUSH_IMAGE_TAR" \
  "$CHANNEL" "${FHD_PUSH_REMOTE_DEPLOY_ROOT:-/opt/fhd-full}" "$GIT_SHA" "$SHA256" \
  "$CONTROLLER_HASHES_B64" "${FHD_PUSH_APPLY_LOCK_WAIT_SECONDS:-360}" <<'REMOTE_PROMOTE'
set -euo pipefail
python3 - "$@" <<'PY_BOOTSTRAP'
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

PROC_ROOT = Path("/proc")
LOCK_PATH = Path("/tmp/fhd-auto-update.lock")
LEGACY_DEPLOY_ROOT = Path("/opt/fhd-full")


def atomic_bytes(path, data, mode):
    fd, tmp = tempfile.mkstemp(prefix=".controller-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def require_real_parents(path):
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise RuntimeError("controller path must not traverse symlinks")


def wait_legacy_exit(controller, deadline):
    if not PROC_ROOT.is_dir():
        raise RuntimeError("cannot establish legacy-controller quiescence")
    while True:
        running = False
        for proc in PROC_ROOT.iterdir():
            if not proc.name.isdigit() or int(proc.name) == os.getpid():
                continue
            try:
                args = (proc / "cmdline").read_bytes().split(b"\0")
            except FileNotFoundError:
                continue
            if os.fsencode(controller) in args:
                running = True
        if not running:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("legacy controller has not exited; manifest stays unchanged")
        time.sleep(0.1)


def bootstrap_promote(args):
    immutable, channel_dir, artifact, image, channel, root, sha, digest, encoded, wait = args
    immutable, channel_dir, root = Path(immutable), Path(channel_dir), Path(root)
    if not all(path.is_absolute() for path in (immutable, channel_dir, root)):
        raise RuntimeError("release paths must be absolute")
    if channel == "stable" and root != LEGACY_DEPLOY_ROOT:
        raise RuntimeError("stable controller root differs from the verified legacy cron target")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", artifact) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("invalid release identity")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not wait.isdigit():
        raise RuntimeError("invalid archive identity or lock wait")
    expected = json.loads(base64.b64decode(encoded, validate=True))
    required = {"fhd-auto-update.sh", "fhd-apply-release.sh", "fhd-apply-release-compose.sh",
                "fhd-load-release-image.sh", "lib/deploy_emit.sh", "lib/autonomy_gate.sh",
                "lib/verify_release_identity.sh", "lib/dora_event.sh", "lib/version.sh",
                "lib/verify_admin_console.py", "lib/mod_tree_guard.py", "lib/verify_release_archive.py",
                "lib/service_quiescence.sh", "lib/apply_recovery.sh", "prune_release_cache.py"}
    if channel == "stable" and (not isinstance(expected, dict) or set(expected) != required):
        raise RuntimeError("stable controller inventory is incomplete or unexpected")
    manifest_path = immutable / "fhd-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest.get("artifact"), manifest.get("git_sha"), manifest.get("sha256")) != (artifact, sha, digest):
        raise RuntimeError("immutable manifest differs from the frozen upload identity")
    lock = None
    try:
        if channel == "stable":
            fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            lock = os.fdopen(fd, "a+")
            deadline = time.monotonic() + int(wait)
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("legacy updater lock timeout; manifest stays unchanged")
                    time.sleep(0.1)
        with (immutable / artifact).open("rb") as stream:
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
            if h.hexdigest() != digest:
                raise RuntimeError("uploaded artifact SHA256 differs from immutable manifest")
            if channel == "stable":
                stream.seek(0)
                with tarfile.open(fileobj=stream, mode="r:*") as archive:
                    selected = {}
                    identity = None
                    for member in archive:
                        name = member.name.removeprefix("./")
                        key = name.removeprefix("scripts/deploy/") if name.startswith("scripts/deploy/") else None
                        if name != ".build-identity.json" and key not in expected:
                            continue
                        if not member.isfile() or member.size > 1024 * 1024 or name in selected:
                            raise RuntimeError("invalid or duplicate controller archive member")
                        data = archive.extractfile(member).read()
                        selected[name] = data
                        if name == ".build-identity.json":
                            identity = json.loads(data)
                    if not identity or identity.get("git_sha") != sha:
                        raise RuntimeError("archive build identity differs from frozen main SHA")
                    payload = {}
                    for name, checksum in expected.items():
                        if name.startswith("/") or ".." in Path(name).parts:
                            raise RuntimeError("invalid controller inventory path")
                        data = selected.get("scripts/deploy/" + name)
                        if data is None or hashlib.sha256(data).hexdigest() != checksum:
                            raise RuntimeError("controller differs from reviewed main source")
                        if name.endswith(".py"):
                            compile(data, name, "exec")
                        else:
                            subprocess.run(["bash", "-n"], input=data, check=True,
                                           env={k:v for k,v in os.environ.items() if k != "BASH_ENV"})
                        payload[name] = data
                deploy = root / "scripts/deploy"
                require_real_parents(deploy)
                backup = root.parent / ("." + root.name + "-controller-backups") / sha
                require_real_parents(backup)
                backup.mkdir(parents=True, exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix="controller-", dir=backup))
                old = {}
                for name in payload:
                    target = deploy / name
                    require_real_parents(target)
                    old[name] = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode)) if target.exists() else None
                    if old[name] is not None:
                        saved = backup / name
                        saved.parent.mkdir(parents=True, exist_ok=True)
                        atomic_bytes(saved, old[name][0], old[name][1])
                        if saved.read_bytes() != old[name][0]:
                            raise RuntimeError("controller backup verification failed")
                atomic_bytes(backup / "backup.json", json.dumps({
                    name: {"sha256": hashlib.sha256(value[0]).hexdigest(), "mode": value[1]}
                    if value is not None else None for name, value in old.items()
                }, sort_keys=True).encode(), 0o600)
                installed = []
                try:
                    for name in sorted(payload, key=lambda value: value == "fhd-auto-update.sh"):
                        target = deploy / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        atomic_bytes(target, payload[name], 0o755 if name.endswith(".sh") else 0o644)
                        installed.append(name)
                        if target.read_bytes() != payload[name]:
                            raise RuntimeError("installed controller verification failed")
                    wait_legacy_exit(deploy / "fhd-auto-update.sh", time.monotonic() + int(wait))
                except BaseException:
                    for name in reversed(installed):
                        target = deploy / name
                        if old[name] is None:
                            target.unlink()
                        else:
                            atomic_bytes(target, *old[name])
                    raise
        # No controller is executed here. Existing freeze and autonomy approval remain authoritative.
        channel_dir.mkdir(parents=True, exist_ok=True)
        names = [artifact] + (["fhd-api-image.tar.gz"] if image == "1" else []) + ["fhd-manifest.json"]
        for name in names:
            target = channel_dir / name
            if name == "fhd-manifest.json":
                atomic_bytes(target, manifest_bytes, 0o644)
                continue
            fd, tmp = tempfile.mkstemp(prefix=".promote-", dir=channel_dir)
            try:
                with os.fdopen(fd, "wb") as output, (immutable / name).open("rb") as source:
                    copied = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        output.write(chunk)
                        copied.update(chunk)
                    if name == artifact and copied.hexdigest() != digest:
                        raise RuntimeError("archive changed before channel promotion")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    bootstrap_promote(sys.argv[1:])
PY_BOOTSTRAP
REMOTE_PROMOTE

if [[ "$APPLY_NOW" == "1" ]]; then
  REMOTE_DEPLOY_ROOT="${FHD_PUSH_REMOTE_DEPLOY_ROOT:-/opt/fhd-full}"
  REMOTE_HEALTH_URL="${FHD_PUSH_HEALTH_URL:-http://127.0.0.1:5100/api/health?lite=true}"
  APPLY_LOCK_WAIT_SECONDS="${FHD_PUSH_APPLY_LOCK_WAIT_SECONDS:-360}"
  HEALTH_RETRIES="${FHD_PUSH_HEALTH_RETRIES:-120}"
  HEALTH_INTERVAL="${FHD_PUSH_HEALTH_INTERVAL:-3}"
  for setting in APPLY_LOCK_WAIT_SECONDS HEALTH_RETRIES HEALTH_INTERVAL; do
    case "${!setting}" in
      '' | *[!0-9]*) echo "[err] FHD_PUSH_$setting 必须为非负整数" >&2; exit 64 ;;
    esac
  done
  if [[ "$HEALTH_RETRIES" -eq 0 ]]; then
    echo "[err] FHD_PUSH_HEALTH_RETRIES 必须为正整数" >&2
    exit 64
  fi
  REMOTE_MANIFEST="${REMOTE_DIR}/fhd-manifest.json"
  REMOTE_TARBALL="${REMOTE_DIR}/${ARTIFACT}"
  printf -v APPLY_COMMAND \
    'set -euo pipefail; BOOTSTRAP=$(mktemp -d /tmp/fhd-release-bootstrap.XXXXXX); trap '\''rm -rf -- "$BOOTSTRAP"'\'' EXIT; tar -xzf %q -C "$BOOTSTRAP" ./scripts/deploy; test -x "$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"; XCMAX_PRESERVE_RELEASE_HISTORY=%q FHD_AUTO_UPDATE_LOCK_WAIT_SECONDS=%q FHD_MANIFEST_PATH=%q FHD_ARTIFACT_DIR=%q FHD_DEPLOY_ROOT=%q bash "$BOOTSTRAP/scripts/deploy/fhd-auto-update.sh"' \
    "$REMOTE_TARBALL" "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" "$APPLY_LOCK_WAIT_SECONDS" "$REMOTE_MANIFEST" "$REMOTE_DIR" "$REMOTE_DEPLOY_ROOT"

  deploy_emit apply started "host=$HOST git_sha=$GIT_SHA mode=${DEPLOY_MODE:-tarball}"
  if ! "${SSH[@]}" "$REMOTE" "$APPLY_COMMAND"; then
    deploy_emit apply failed "remote_auto_update_failed"
    echo "[err] 远端自动应用失败；发布未通过" >&2
    exit 1
  fi

  EXPECTED_RUNTIME_IMAGE_DIGEST=""
  if [[ "${DEPLOY_MODE:-tarball}" == "image" ]]; then
    EXPECTED_RUNTIME_IMAGE_DIGEST="${IMAGE_DIGEST:-}"
  fi
  deploy_emit verify started \
    "url=$REMOTE_HEALTH_URL git_sha=$GIT_SHA retries=$HEALTH_RETRIES interval=${HEALTH_INTERVAL}s"
  printf -v HEALTH_COMMAND 'curl --noproxy "*" -fsS --max-time 10 %q 2>/dev/null' "$REMOTE_HEALTH_URL"
  REMOTE_HEALTH_PAYLOAD=""
  HEALTH_STATE="remote_health_unreachable"
  HEALTH_READY=0
  for ((attempt = 1; attempt <= HEALTH_RETRIES; attempt++)); do
    if REMOTE_HEALTH_PAYLOAD="$("${SSH[@]}" "$REMOTE" "$HEALTH_COMMAND")"; then
      HEALTH_STATE="remote_identity_mismatch"
      if verify_release_identity_payload \
          "$REMOTE_HEALTH_PAYLOAD" \
          "$GIT_SHA" \
          "$EXPECTED_RUNTIME_IMAGE_DIGEST" \
          "$SHA256" \
          "$ADMIN_CONSOLE_SHA256"; then
        HEALTH_READY=1
        break
      fi
    fi
    if [[ "$attempt" -lt "$HEALTH_RETRIES" ]]; then
      sleep "$HEALTH_INTERVAL"
    fi
  done
  if [[ "$HEALTH_READY" != "1" ]]; then
    deploy_emit verify failed "$HEALTH_STATE attempts=$HEALTH_RETRIES"
    echo "[err] 远端 exact-SHA 健康身份在 ${HEALTH_RETRIES} 次探测内未就绪；发布未通过" >&2
    exit 1
  fi
  deploy_emit verify ok "git_sha=$GIT_SHA"
  deploy_emit apply ok "host=$HOST git_sha=$GIT_SHA"

  # Bound successful release history only when this invocation permits pruning.
  if [[ "${XCMAX_PRESERVE_RELEASE_HISTORY:-0}" != 1 ]]; then
    REMOTE_PRUNER="${REMOTE_DEPLOY_ROOT}/scripts/deploy/prune_release_cache.py"
    if ! "${SSH[@]}" "$REMOTE" \
        "python3 '$REMOTE_PRUNER' --release-dir '$REMOTE_DIR' --backup-dir '/opt/fhd-full-backups' --current-artifact '$ARTIFACT' --retain-releases 8 --retain-backups 5 --part-max-age-hours 24"; then
      echo "[warn] release cache cleanup failed after verified deploy; runtime remains healthy" >&2
    fi
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
