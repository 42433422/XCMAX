#!/usr/bin/env bash
# Android 实验骨架交付冒烟（文档 SSOT + 本地构建）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "[android-smoke] verify 实验骨架诚实标注（非签约级）"
grep -q "实验骨架" VERSION.md
grep -q "实验骨架" mobile-android/README.md
grep -qE "非.*签约级" mobile-android/README.md
test -f docs/guides/MOBILE_ANDROID.md

echo "[android-smoke] verify version anchors"
python3 scripts/dev/verify_version_anchors.py

java_ok=false
if [ -n "${JAVA_HOME:-}" ] && [ -x "${JAVA_HOME}/bin/java" ]; then
  java_ok=true
elif command -v java >/dev/null 2>&1 && java -version >/dev/null 2>&1; then
  java_ok=true
fi

if [ "$java_ok" != true ]; then
  echo "[android-smoke] SKIP gradle: no Java runtime (doc checks OK)"
  echo "[android-smoke] OK (doc-only)"
  exit 0
fi

# shellcheck source=/dev/null
source "$ROOT/scripts/dev/android_env.sh" 2>/dev/null || true

echo "[android-smoke] gradle assemble + unit tests"
cd mobile-android
GRADLE_INIT=""
if [ -f ".toolchain/gradle-mirror.init.gradle" ]; then
  GRADLE_INIT="--init-script .toolchain/gradle-mirror.init.gradle"
fi
./gradlew $GRADLE_INIT assemblePersonalDebug assembleEnterpriseDebug testPersonalDebugUnitTest --quiet

echo "[android-smoke] OK"
