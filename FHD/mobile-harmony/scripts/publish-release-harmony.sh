#!/usr/bin/env bash
set -euo pipefail

VERSION="10.0.0"
TAG="FHD/v10.0.0"
REPO="${GITHUB_REPOSITORY:-42433422/XCMAX}"
HARMONY_ARTIFACT=""
APK_PATH=""
SKIP_BUILD=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: publish-release-harmony.sh [--version <10.0.0>] [--tag <FHD/v10.0.0>] \
  [--repo <owner/name>] [--harmony-artifact <path>] [--apk-path <path>] [--skip-build] [--dry-run]

Build or publish a real XCAGI Enterprise HarmonyOS artifact to the GitHub release.

If --harmony-artifact is omitted, this script runs scripts/build-hap.sh and uses
the generated artifacts/XCAGI-Enterprise-Harmony-<VERSION>.hap.

The script downloads the current enterprise Android APK from the release when
--apk-path is omitted, regenerates XCAGI-Enterprise-Mobile-Packages-v<VERSION>.zip
with both Android and Harmony artifacts, then uploads:
  - XCAGI-Enterprise-Harmony-<VERSION>.<hap|hsp>
  - XCAGI-Enterprise-Mobile-Packages-v<VERSION>.zip
USAGE
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      ;;
    --version|-v)
      VERSION="${2:-}"
      shift 2
      ;;
    --tag)
      TAG="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --harmony-artifact)
      HARMONY_ARTIFACT="${2:-}"
      shift 2
      ;;
    --apk-path)
      APK_PATH="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

normalize_version() {
  local value="$1"
  value="${value#FHD/}"
  value="${value#v}"
  value="${value#V}"
  printf '%s' "$value"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FHD_ROOT="$(cd "${MODULE_ROOT}/.." && pwd)"
REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
VERSION="$(normalize_version "$VERSION")"
[[ -n "$VERSION" ]] || VERSION="10.0.0"
[[ -n "$TAG" ]] || TAG="FHD/v${VERSION}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Missing gh CLI; cannot upload GitHub release assets." >&2
  exit 127
fi

if [[ -z "$HARMONY_ARTIFACT" && "$SKIP_BUILD" -eq 0 ]]; then
  HARMONY_ARTIFACT="$(find "${MODULE_ROOT}/artifacts" -type f \( -name "*.hap" -o -name "*.hsp" \) -print 2>/dev/null | sort | tail -1)"
fi

if [[ -z "$HARMONY_ARTIFACT" && "$SKIP_BUILD" -eq 0 ]]; then
  HARMONY_ARTIFACT="$("${SCRIPT_DIR}/build-hap.sh" --version "$VERSION" --mode release | tail -1)"
fi

if [[ -z "$HARMONY_ARTIFACT" || ! -f "$HARMONY_ARTIFACT" ]]; then
  echo "Missing HarmonyOS .hap/.hsp artifact. Pass --harmony-artifact or install the HarmonyOS build toolchain." >&2
  exit 1
fi

if [[ "$(basename "$HARMONY_ARTIFACT")" == *unsigned* && "${HARMONY_ALLOW_UNSIGNED:-0}" != "1" ]]; then
  echo "Refusing to publish unsigned HarmonyOS artifact: ${HARMONY_ARTIFACT}" >&2
  echo "Configure HarmonyOS signing or set HARMONY_ALLOW_UNSIGNED=1 for local smoke packaging only." >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

if [[ -z "$APK_PATH" ]]; then
  gh release download "$TAG" \
    --repo "$REPO" \
    --pattern "XCAGI-Enterprise-Android-${VERSION}.apk" \
    --dir "$WORK_DIR"
  APK_PATH="${WORK_DIR}/XCAGI-Enterprise-Android-${VERSION}.apk"
fi

if [[ ! -f "$APK_PATH" ]]; then
  echo "Missing enterprise Android APK: ${APK_PATH}" >&2
  exit 1
fi

"${SCRIPT_DIR}/stage-release-packages.sh" \
  --version "$VERSION" \
  --android-version "$VERSION" \
  --apk-path "$APK_PATH" \
  --harmony-artifact "$HARMONY_ARTIFACT"

HARMONY_EXT="${HARMONY_ARTIFACT##*.}"
HARMONY_RELEASE_NAME="XCAGI-Enterprise-Harmony-${VERSION}.${HARMONY_EXT}"
STAGED_HARMONY="${REPO_ROOT}/release/packages-v${VERSION}/enterprise/${HARMONY_RELEASE_NAME}"
ZIP_PATH="${REPO_ROOT}/release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip"

test -f "$STAGED_HARMONY"
test -f "$ZIP_PATH"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry run: staged HarmonyOS release assets without uploading:"
  echo "  ${STAGED_HARMONY}"
  echo "  ${ZIP_PATH}"
  exit 0
fi

gh release upload "$TAG" "$STAGED_HARMONY" "$ZIP_PATH" \
  --repo "$REPO" \
  --clobber

ASSET_NAMES="$(gh release view "$TAG" --repo "$REPO" --json assets --jq '.assets[].name')"
printf '%s\n' "$ASSET_NAMES" | grep -Fx "$HARMONY_RELEASE_NAME" >/dev/null
printf '%s\n' "$ASSET_NAMES" | grep -Fx "$(basename "$ZIP_PATH")" >/dev/null

echo "Published HarmonyOS release assets to ${REPO} ${TAG}:"
echo "  ${HARMONY_RELEASE_NAME}"
echo "  $(basename "$ZIP_PATH")"
