#!/bin/bash
set -euo pipefail

VERSION="10.0.0"
INPUT_HAP=""
OUTPUT_HAP=""
BUNDLE_NAME="com.xiuci.xcagi.mobile.enterprise"
SIGNING_DIR="${HOME}/XCMAX-runtime/harmony/signing"
TOOLCHAIN_LIB=""

usage() {
  cat <<'USAGE'
Usage: sign-openharmony-debug-hap.sh [--version <10.0.0>] [--input <entry-default-unsigned.hap>] [--output <XCAGI-Enterprise-Harmony-10.0.0.hap>]

Sign the locally built XCAGI Enterprise HarmonyOS HAP with the OpenHarmony debug
certificate bundled in the HarmonyOS command-line tools, then verify the signed
artifact with hap-sign-tool.

This is a local/debug signature for test installation. Production Huawei AppGallery
Connect signing must be configured separately with a real HarmonyOS certificate
and provisioning profile.
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
    --input)
      INPUT_HAP="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_HAP="${2:-}"
      shift 2
      ;;
    --bundle-name)
      BUNDLE_NAME="${2:-}"
      shift 2
      ;;
    --signing-dir)
      SIGNING_DIR="${2:-}"
      shift 2
      ;;
    --toolchain-lib)
      TOOLCHAIN_LIB="${2:-}"
      shift 2
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

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 127
  fi
}

find_default_toolchain_lib() {
  local candidate
  for candidate in \
    "${HOME}/XCMAX-runtime/harmony/command-line-tools/sdk/default/openharmony/toolchains/lib" \
    "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/lib" \
    "/Applications/DevEco Studio.app/Contents/sdk/default/openharmony/toolchains/lib" \
    "/Applications/Huawei DevEco Studio.app/Contents/sdk/default/openharmony/toolchains/lib"; do
    if [[ -f "${candidate}/hap-sign-tool.jar" && -f "${candidate}/OpenHarmony.p12" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

find_latest_unsigned_hap() {
  find "${MODULE_ROOT}" -type f -name "*unsigned*.hap" -path "*/build/*" -print 2>/dev/null | sort | tail -1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="$(normalize_version "$VERSION")"
[[ -n "$VERSION" ]] || VERSION="10.0.0"
[[ -n "$INPUT_HAP" ]] || INPUT_HAP="$(find_latest_unsigned_hap)"
[[ -n "$OUTPUT_HAP" ]] || OUTPUT_HAP="${MODULE_ROOT}/artifacts/XCAGI-Enterprise-Harmony-${VERSION}.hap"
[[ -n "$TOOLCHAIN_LIB" ]] || TOOLCHAIN_LIB="$(find_default_toolchain_lib || true)"

if [[ -z "$INPUT_HAP" || ! -f "$INPUT_HAP" ]]; then
  echo "Missing unsigned HAP. Run hvigor assembleHap first or pass --input." >&2
  exit 1
fi

if [[ -z "$TOOLCHAIN_LIB" || ! -d "$TOOLCHAIN_LIB" ]]; then
  echo "Unable to locate HarmonyOS OpenHarmony toolchain lib directory." >&2
  exit 1
fi

HAP_SIGN_TOOL="${TOOLCHAIN_LIB}/hap-sign-tool.jar"
OPENHARMONY_KEYSTORE="${TOOLCHAIN_LIB}/OpenHarmony.p12"
PROFILE_CERT_FILE="${TOOLCHAIN_LIB}/OpenHarmonyProfileDebug.pem"
PROFILE_TEMPLATE="${TOOLCHAIN_LIB}/UnsgnedDebugProfileTemplate.json"

for required in "$HAP_SIGN_TOOL" "$OPENHARMONY_KEYSTORE" "$PROFILE_CERT_FILE" "$PROFILE_TEMPLATE"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing HarmonyOS signing file: ${required}" >&2
    exit 1
  fi
done

require_command java
require_command keytool
require_command node

mkdir -p "$SIGNING_DIR" "$(dirname "$OUTPUT_HAP")"

PROFILE_JSON="${SIGNING_DIR}/xcagi-debug-profile.json"
SIGNED_PROFILE="${SIGNING_DIR}/xcagi-debug-profile.p7b"
APP_CERT_PEM="${SIGNING_DIR}/xcagi-app-debug-cert.pem"
APP_ROOT_CA="${SIGNING_DIR}/openharmony-app-root-ca.cer"
APP_CA="${SIGNING_DIR}/openharmony-app-ca.cer"
APP_CERT_CHAIN="${SIGNING_DIR}/xcagi-app-debug-cert-chain.cer"
VERIFY_CERT_CHAIN="${SIGNING_DIR}/verify-cert-chain.cer"
VERIFY_PROFILE="${SIGNING_DIR}/verify-profile.p7b"

PROFILE_TEMPLATE="$PROFILE_TEMPLATE" \
PROFILE_JSON="$PROFILE_JSON" \
APP_CERT_PEM="$APP_CERT_PEM" \
BUNDLE_NAME="$BUNDLE_NAME" \
VERSION="$VERSION" \
node <<'NODE'
const fs = require('fs');
const crypto = require('crypto');

const profile = JSON.parse(fs.readFileSync(process.env.PROFILE_TEMPLATE, 'utf8'));
const version = process.env.VERSION || '10.0.0';
const versionCode = version.split('.').reduce((acc, part) => {
  const value = Number.parseInt(part, 10);
  return acc * 100 + (Number.isFinite(value) ? value : 0);
}, 0);
const now = Math.floor(Date.now() / 1000);

profile['version-name'] = version;
profile['version-code'] = Math.max(versionCode, 1);
profile.uuid = crypto.randomUUID();
profile.validity = {
  'not-before': now - 3600,
  'not-after': now + 366 * 24 * 3600
};
profile['bundle-info']['bundle-name'] = process.env.BUNDLE_NAME;

fs.writeFileSync(process.env.PROFILE_JSON, JSON.stringify(profile, null, 2));
fs.writeFileSync(process.env.APP_CERT_PEM, profile['bundle-info']['development-certificate']);
NODE

keytool -exportcert \
  -rfc \
  -keystore "$OPENHARMONY_KEYSTORE" \
  -storetype PKCS12 \
  -storepass 123456 \
  -alias "openharmony application root ca" \
  -file "$APP_ROOT_CA" >/dev/null

keytool -exportcert \
  -rfc \
  -keystore "$OPENHARMONY_KEYSTORE" \
  -storetype PKCS12 \
  -storepass 123456 \
  -alias "openharmony application ca" \
  -file "$APP_CA" >/dev/null

java -jar "$HAP_SIGN_TOOL" sign-profile \
  -mode localSign \
  -keyAlias "openharmony application profile debug" \
  -keyPwd 123456 \
  -profileCertFile "$PROFILE_CERT_FILE" \
  -inFile "$PROFILE_JSON" \
  -signAlg SHA256withECDSA \
  -keystoreFile "$OPENHARMONY_KEYSTORE" \
  -keystorePwd 123456 \
  -outFile "$SIGNED_PROFILE"

java -jar "$HAP_SIGN_TOOL" generate-app-cert \
  -keyAlias "openharmony application release" \
  -keyPwd 123456 \
  -issuer "C=CN,O=OpenHarmony,OU=OpenHarmony Team,CN=OpenHarmony Application CA" \
  -issuerKeyAlias "openharmony application ca" \
  -issuerKeyPwd 123456 \
  -subject "C=CN,O=OpenHarmony,OU=OpenHarmony Team,CN=OpenHarmony Application Release" \
  -validity 365 \
  -signAlg SHA256withECDSA \
  -rootCaCertFile "$APP_ROOT_CA" \
  -subCaCertFile "$APP_CA" \
  -keystoreFile "$OPENHARMONY_KEYSTORE" \
  -keystorePwd 123456 \
  -outForm certChain \
  -outFile "$APP_CERT_CHAIN"

java -jar "$HAP_SIGN_TOOL" sign-app \
  -mode localSign \
  -keyAlias "openharmony application release" \
  -keyPwd 123456 \
  -appCertFile "$APP_CERT_CHAIN" \
  -profileFile "$SIGNED_PROFILE" \
  -inFile "$INPUT_HAP" \
  -signAlg SHA256withECDSA \
  -keystoreFile "$OPENHARMONY_KEYSTORE" \
  -keystorePwd 123456 \
  -outFile "$OUTPUT_HAP" \
  -compatibleVersion 12 \
  -signCode 1

java -jar "$HAP_SIGN_TOOL" verify-app \
  -inFile "$OUTPUT_HAP" \
  -outCertChain "$VERIFY_CERT_CHAIN" \
  -outProfile "$VERIFY_PROFILE"

echo "$OUTPUT_HAP"
