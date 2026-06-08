#!/usr/bin/env bash
# Android 签约级交付冒烟（文档 SSOT + 本地构建）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "[android-smoke] verify VERSION.md 签约级表述"
grep -q "签约级" VERSION.md
grep -q "签约级" mobile-android/README.md
test -f docs/guides/MOBILE_ANDROID.md

echo "[android-smoke] verify version anchors"
python3 scripts/dev/verify_version_anchors.py

echo "[android-smoke] gradle assemble + unit tests"
# shellcheck source=/dev/null
source "$ROOT/scripts/dev/android_env.sh"
cd mobile-android
GRADLE_INIT=""
if [ -f ".toolchain/gradle-mirror.init.gradle" ]; then
  GRADLE_INIT="--init-script .toolchain/gradle-mirror.init.gradle"
fi
./gradlew $GRADLE_INIT assemblePersonalDebug assembleEnterpriseDebug testPersonalDebugUnitTest --quiet

echo "[android-smoke] OK"
