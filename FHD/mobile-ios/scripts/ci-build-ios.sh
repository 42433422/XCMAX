#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "xcodegen is required. Install with: brew install xcodegen" >&2
  exit 127
fi

bash scripts/generate-app-icon.sh
xcodegen generate

marketing_version="${IOS_MARKETING_VERSION:-10.0.0}"
build_number="${IOS_BUILD_NUMBER:-1}"
destination="${IOS_SIMULATOR_DESTINATION:-generic/platform=iOS Simulator}"
schemes="${IOS_SCHEMES:-XCAGIMobile XCAGIMobilePersonal}"

for scheme in ${schemes}; do
  xcodebuild \
    -project XCAGIMobile.xcodeproj \
    -scheme "${scheme}" \
    -configuration Debug \
    -sdk iphonesimulator \
    -destination "${destination}" \
    MARKETING_VERSION="${marketing_version}" \
    CURRENT_PROJECT_VERSION="${build_number}" \
    CODE_SIGNING_ALLOWED=NO \
    build
done
