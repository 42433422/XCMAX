#!/usr/bin/env bash
# 本地 Android 构建/冒烟环境（source 后生效）
FHD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -x "${FHD_ROOT}/.tools/jdk-17/Contents/Home/bin/java" ]; then
  export JAVA_HOME="${FHD_ROOT}/.tools/jdk-17/Contents/Home"
elif [ -z "${JAVA_HOME:-}" ]; then
  export JAVA_HOME="${FHD_ROOT}/.tools/jdk-17/Contents/Home"
fi
export ANDROID_HOME="${ANDROID_HOME:-${FHD_ROOT}/mobile-android/.toolchain/android-sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
export PATH="${JAVA_HOME}/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"
