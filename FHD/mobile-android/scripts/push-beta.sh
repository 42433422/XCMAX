#!/usr/bin/env bash
# 一键推送 beta：时间戳当 versionCode(每次自增,不被版本号卡死) + beta versionName →
# 构建 enterpriseDebug → 上传到 xiu-ci.com → 同步服务器版本号 + 重启 modstore → 清理旧 beta。
# 手机端"关于→检查更新"即可拉到(force 空=可选)。需要密码文件：默认 /tmp/.sshpw（可用 SSH_PW_FILE 指定）。
set -euo pipefail

HOST="${BETA_SSH_HOST:-root@119.27.178.147}"
PWF="${SSH_PW_FILE:-/tmp/.sshpw}"
ENVPATH='/root/XCMAX/成都修茈科技有限公司/MODstore_deploy/.env'
RELDIR='/var/www/update/releases/stable/enterprise'
KEEP="${BETA_KEEP:-3}"   # 服务器上保留最近几个 beta

[ -f "$PWF" ] || { echo "缺少密码文件 $PWF（写入服务器 root 密码，chmod 600）"; exit 1; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"   # mobile-android 根
TMPD="$(mktemp -d)"
ASK=""
cleanup() { [ -n "${ASK:-}" ] && rm -f "$ASK"; rm -rf "$TMPD"; }
trap cleanup EXIT
STAMP="$(date +%s)"
VN="${1:-11.0.0-beta.$STAMP}"              # 可传自定义 versionName 作首参
APK_NAME="XCAGI-Enterprise-Android-$VN.apk"
PATCH_NAME=""
DELTA_READY=0

CONFIG_JSON="$TMPD/current-config.json"
curl -fsS 'https://xiu-ci.com/api/app/config?platform=android&sku=enterprise' > "$CONFIG_JSON" 2>/dev/null || true
OLD_VC="$(python3 - "$CONFIG_JSON" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("latest_android_version", ""))
except Exception:
    print("")
PY
)"
OLD_VN="$(python3 - "$CONFIG_JSON" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("latest_android_version_name", ""))
except Exception:
    print("")
PY
)"
OLD_APK_URL="$(python3 - "$CONFIG_JSON" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("apk_download_url", ""))
except Exception:
    print("")
PY
)"

echo "==> 构建 beta versionCode=$STAMP versionName=$VN"
( cd "$HERE" && XCMAX_VC="$STAMP" XCMAX_VN="$VN" ./gradlew :app:assembleEnterpriseDebug --console=plain -q )
APK="$HERE/app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk"
[ -f "$APK" ] || { echo "构建产物缺失 $APK"; exit 1; }

if [ -n "$OLD_VC" ] && [ -n "$OLD_VN" ] && [ -n "$OLD_APK_URL" ] && [ "$OLD_VC" != "$STAMP" ]; then
  SAFE_OLD="$(printf '%s' "$OLD_VN" | tr -c 'A-Za-z0-9._-' '_')"
  SAFE_NEW="$(printf '%s' "$VN" | tr -c 'A-Za-z0-9._-' '_')"
  PATCH_NAME="XCAGI-Enterprise-Android-${SAFE_OLD}-to-${SAFE_NEW}.xcapkdiff"
  OLD_APK="$TMPD/old.apk"
  PATCH="$TMPD/$PATCH_NAME"
  DELTA_MANIFEST="$TMPD/android_delta_manifest.json"
  echo "==> 生成增量包 base=$OLD_VN($OLD_VC) -> target=$VN($STAMP)"
  if curl -fL "$OLD_APK_URL" -o "$OLD_APK"; then
    python3 "$HERE/scripts/make-apk-delta.py" \
      --old "$OLD_APK" \
      --new "$APK" \
      --patch "$PATCH" \
      --manifest "$DELTA_MANIFEST" \
      --base-code "$OLD_VC" \
      --base-name "$OLD_VN" \
      --target-code "$STAMP" \
      --target-name "$VN" \
      --patch-url "https://xiu-ci.com/download/enterprise/$PATCH_NAME" \
      --sku enterprise || true
    [ -f "$PATCH" ] && [ -f "$DELTA_MANIFEST" ] && DELTA_READY=1
  else
    echo "WARN: 旧 APK 下载失败，跳过增量包"
  fi
fi

# 无 pty 的密码 ssh：SSH_ASKPASS（见 mobile-ota-self-update 记忆）
ASK=/tmp/.beta_askpass.sh
printf '#!/bin/bash\ncat %q\n' "$PWF" > "$ASK"; chmod +x "$ASK"
export SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force
SSHO=(-o StrictHostKeyChecking=no -o ConnectTimeout=25)

echo "==> 上传 $APK_NAME"
scp "${SSHO[@]}" "$APK" "$HOST:$RELDIR/$APK_NAME" < /dev/null
if [ "$DELTA_READY" = "1" ]; then
  echo "==> 上传增量包 $PATCH_NAME"
  scp "${SSHO[@]}" "$PATCH" "$HOST:$RELDIR/$PATCH_NAME" < /dev/null
  scp "${SSHO[@]}" "$DELTA_MANIFEST" "$HOST:$RELDIR/android_delta_manifest.json" < /dev/null
fi

echo "==> 同步服务器版本号 + 重启 + 清理旧 beta"
ssh "${SSHO[@]}" "$HOST" "
set -e
sed -i 's#^XCAGI_ANDROID_LATEST_VERSION_CODE=.*#XCAGI_ANDROID_LATEST_VERSION_CODE=$STAMP#g; s#^XCAGI_ANDROID_LATEST_VERSION_NAME=.*#XCAGI_ANDROID_LATEST_VERSION_NAME=$VN#g' '$ENVPATH'
systemctl restart modstore
ls -t '$RELDIR'/XCAGI-Enterprise-Android-*-beta.*.apk 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
ls -t '$RELDIR'/XCAGI-Enterprise-Android-*.xcapkdiff 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
sleep 8
curl -s 'http://127.0.0.1:9999/api/app/config?platform=android&sku=enterprise' || true
" < /dev/null
echo ""
echo "==> 完成。手机：关于→检查更新 → 发现新版本 $VN → 去更新"
