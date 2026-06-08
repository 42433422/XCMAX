#!/bin/sh
# Called by sync-modstore-to-server.ps1 after:
#  - /tmp/remote_sync_remote_base (UTF-8, one line) = parent of MODstore_deploy
#  - /tmp/remote_sync_extract.sh = remote_sync_extract.sh
# Avoids JSON/SSH mangling of non-ASCII in REMOTE_BASE.
set -e
if [ ! -f /tmp/remote_sync_remote_base ]; then
  echo "[err] missing /tmp/remote_sync_remote_base" >&2
  exit 1
fi
# 文件内为 UTF-8 路径的 base64（ASCII 一行），避免本机/远端编码不一致把中文路径读乱
b64=$(tr -d '\n\r' </tmp/remote_sync_remote_base)
rm -f /tmp/remote_sync_remote_base
if ! rb=$(printf '%s' "$b64" | base64 -d 2>/dev/null); then
  echo "[err] base64 -d failed (install coreutils?)" >&2
  exit 1
fi
export REMOTE_BASE="${rb}"
# sync-modstore-to-server.ps1 经本脚本调用全链发布；与 remote_sync_extract 的「弃用护栏」配套
export MODSTORE_ALLOW_LEGACY_FULLCHAIN=1
chmod +x /tmp/remote_sync_extract.sh
bash /tmp/remote_sync_extract.sh
s=$?
rm -f /tmp/remote_sync_extract.sh
exit $s
