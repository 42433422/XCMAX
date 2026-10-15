#!/usr/bin/env bash
# Windows 安装包唯一实现是原生 WPF 构建入口，禁止交叉编译旧 NSIS 包交付。
set -euo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) ;;
  *) echo 'Build the modern WPF installer with build-installer.ps1 on Windows.' >&2; exit 2 ;;
esac
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "${ROOT}/scripts/deploy/lib/version.sh"
SHELL_EXE="$(command -v pwsh || command -v powershell)"
exec "${SHELL_EXE}" -NoProfile -File "$(cygpath -w "${ROOT}/scripts/package/build-installer.ps1")" \
  -Version "${1:-$(product_version)}" -ProductSku "${2:-enterprise}"
