#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

scheme="${IOS_SCHEME:-XCAGIMobile}"
configuration="${IOS_CONFIGURATION:-Release}"
team_id="${IOS_TEAM_ID:-}"
marketing_version="${IOS_MARKETING_VERSION:-10.0.0}"
build_number="${IOS_BUILD_NUMBER:-$(date +%Y%m%d%H%M)}"
archive_path="${IOS_ARCHIVE_PATH:-${ROOT}/build/archives/${scheme}.xcarchive}"
export_path="${IOS_EXPORT_PATH:-${ROOT}/build/export/${scheme}}"
export_method="${IOS_EXPORT_METHOD:-app-store-connect}"
profile_specifier="${IOS_PROVISIONING_PROFILE_SPECIFIER:-}"
upload="${IOS_UPLOAD_APP_STORE_CONNECT:-0}"
skip_export=0

for arg in "$@"; do
  case "${arg}" in
    --no-export) skip_export=1 ;;
    --export) skip_export=0 ;;
    *) echo "Unknown argument: ${arg}" >&2; exit 2 ;;
  esac
done

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "xcodegen is required. Install with: brew install xcodegen" >&2
  exit 127
fi

if [[ -z "${team_id}" ]]; then
  echo "IOS_TEAM_ID is required for device archive/export." >&2
  exit 2
fi

case "${scheme}" in
  XCAGIMobile) bundle_id="com.xiuci.xcagi.mobile.enterprise" ;;
  XCAGIMobilePersonal) bundle_id="com.xiuci.xcagi.mobile.personal" ;;
  *)
    echo "Unknown iOS scheme for provisioning profile mapping: ${scheme}" >&2
    exit 2
    ;;
esac

bash scripts/generate-app-icon.sh
xcodegen generate
mkdir -p "$(dirname "${archive_path}")" "${export_path}" build

signing_args=(
  "DEVELOPMENT_TEAM=${team_id}"
  "MARKETING_VERSION=${marketing_version}"
  "CURRENT_PROJECT_VERSION=${build_number}"
)
if [[ -n "${profile_specifier}" ]]; then
  signing_args+=(
    "CODE_SIGN_STYLE=Manual"
    "PROVISIONING_PROFILE_SPECIFIER=${profile_specifier}"
    "CODE_SIGN_IDENTITY=Apple Distribution"
  )
else
  signing_args+=("CODE_SIGN_STYLE=Automatic")
fi

xcodebuild \
  -project XCAGIMobile.xcodeproj \
  -scheme "${scheme}" \
  -configuration "${configuration}" \
  -destination "generic/platform=iOS" \
  -archivePath "${archive_path}" \
  "${signing_args[@]}" \
  -allowProvisioningUpdates \
  clean archive

if [[ "${skip_export}" == "1" ]]; then
  echo "Archive ready: ${archive_path}"
  exit 0
fi

export_options="${ROOT}/build/ExportOptions-${scheme}.plist"
if [[ -n "${profile_specifier}" ]]; then
  provisioning_profiles_xml=$(cat <<PLIST
  <key>provisioningProfiles</key>
  <dict>
    <key>${bundle_id}</key>
    <string>${profile_specifier}</string>
  </dict>
PLIST
)
else
  provisioning_profiles_xml=""
fi

cat > "${export_options}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>destination</key>
  <string>export</string>
  <key>method</key>
  <string>${export_method}</string>
  <key>signingStyle</key>
  <string>$( [[ -n "${profile_specifier}" ]] && echo manual || echo automatic )</string>
${provisioning_profiles_xml}
  <key>stripSwiftSymbols</key>
  <true/>
  <key>teamID</key>
  <string>${team_id}</string>
</dict>
</plist>
PLIST

xcodebuild \
  -exportArchive \
  -archivePath "${archive_path}" \
  -exportPath "${export_path}" \
  -exportOptionsPlist "${export_options}" \
  -allowProvisioningUpdates

ipa="$(find "${export_path}" -maxdepth 1 -name '*.ipa' -print -quit)"
if [[ -z "${ipa}" ]]; then
  echo "Export finished but no ipa was found in ${export_path}" >&2
  exit 1
fi
echo "IPA ready: ${ipa}"

if [[ "${upload}" == "1" ]]; then
  : "${APP_STORE_CONNECT_API_KEY_ID:?APP_STORE_CONNECT_API_KEY_ID is required}"
  : "${APP_STORE_CONNECT_API_ISSUER_ID:?APP_STORE_CONNECT_API_ISSUER_ID is required}"

  if [[ -n "${APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64:-}" ]]; then
    mkdir -p "${HOME}/.appstoreconnect/private_keys"
    echo "${APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64}" | base64 --decode > "${HOME}/.appstoreconnect/private_keys/AuthKey_${APP_STORE_CONNECT_API_KEY_ID}.p8"
    chmod 600 "${HOME}/.appstoreconnect/private_keys/AuthKey_${APP_STORE_CONNECT_API_KEY_ID}.p8"
  fi

  if ! xcrun iTMSTransporter \
    -m upload \
    -assetFile "${ipa}" \
    -apiKey "${APP_STORE_CONNECT_API_KEY_ID}" \
    -apiIssuer "${APP_STORE_CONNECT_API_ISSUER_ID}"; then
    echo "iTMSTransporter upload failed; retrying with xcrun altool --upload-package." >&2
    xcrun altool \
      --upload-package "${ipa}" \
      --api-key "${APP_STORE_CONNECT_API_KEY_ID}" \
      --api-issuer "${APP_STORE_CONNECT_API_ISSUER_ID}" \
      --verbose
  fi
fi
