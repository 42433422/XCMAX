#!/usr/bin/env bash
# 本地 Android 构建/冒烟环境（source 后生效）
FHD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export JAVA_HOME="${JAVA_HOME:-${FHD_ROOT}/.tools/jdk-17/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-${FHD_ROOT}/mobile-android/.toolchain/android-sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME}}"
export PATH="${JAVA_HOME}/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"
