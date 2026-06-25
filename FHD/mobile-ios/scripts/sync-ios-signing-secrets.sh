#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/sync-ios-signing-secrets.sh \
    --team-id <TEAM_ID> \
    --p12 <certificate.p12> \
    --p12-password <password> \
    --profile-enterprise <enterprise.mobileprovision> \
    [--profile-personal <personal.mobileprovision>] \
    --api-key-p8 <AuthKey_XXXXXX.p8> \
    --api-key-id <KEY_ID> \
    --api-issuer-id <ISSUER_ID> \
    --keychain-password <password> \
    [--repo owner/repo] \
    [--no-legacy-profile-secret] \
    [--dry-run]

The script verifies:
  - the P12 can be decoded,
  - the enterprise provisioning profile matches the current main-line bundle ID,
  - the enterprise provisioning profile embeds the same certificate serial as the P12,
  - when provided, the personal provisioning profile also matches its frozen compatibility bundle ID.

If not in --dry-run mode, it updates GitHub Actions secrets with gh CLI.
EOF
}

repo=""
team_id=""
p12=""
p12_password=""
profile_enterprise=""
profile_personal=""
api_key_p8=""
api_key_id=""
api_issuer_id=""
keychain_password=""
set_legacy_profile_secret=1
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="${2:-}"; shift 2 ;;
    --team-id) team_id="${2:-}"; shift 2 ;;
    --p12) p12="${2:-}"; shift 2 ;;
    --p12-password) p12_password="${2:-}"; shift 2 ;;
    --profile-enterprise) profile_enterprise="${2:-}"; shift 2 ;;
    --profile-personal) profile_personal="${2:-}"; shift 2 ;;
    --api-key-p8) api_key_p8="${2:-}"; shift 2 ;;
    --api-key-id) api_key_id="${2:-}"; shift 2 ;;
    --api-issuer-id) api_issuer_id="${2:-}"; shift 2 ;;
    --keychain-password) keychain_password="${2:-}"; shift 2 ;;
    --no-legacy-profile-secret) set_legacy_profile_secret=0; shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in team_id p12 p12_password profile_enterprise api_key_p8 api_key_id api_issuer_id keychain_password; do
  if [[ -z "${!required}" ]]; then
    echo "Missing required argument: ${required}" >&2
    usage >&2
    exit 2
  fi
done

for path_arg in p12 profile_enterprise api_key_p8; do
  if [[ ! -f "${!path_arg}" ]]; then
    echo "File not found: ${!path_arg}" >&2
    exit 2
  fi
done

if [[ -n "${profile_personal}" && ! -f "${profile_personal}" ]]; then
  echo "File not found: ${profile_personal}" >&2
  exit 2
fi

if [[ -z "${repo}" ]]; then
  repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
fi

if [[ -z "${repo}" && "${dry_run}" -eq 0 ]]; then
  echo "Unable to resolve GitHub repo. Pass --repo owner/repo." >&2
  exit 2
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

b64_file() {
  base64 < "$1" | tr -d '\n'
}

cert_serial_from_p12() {
  openssl pkcs12 -in "$1" -clcerts -nokeys -passin "pass:$2" 2>/dev/null \
    | openssl x509 -noout -serial \
    | cut -d= -f2
}

cert_fingerprint_from_p12() {
  openssl pkcs12 -in "$1" -clcerts -nokeys -passin "pass:$2" 2>/dev/null \
    | openssl x509 -noout -fingerprint -sha1 \
    | cut -d= -f2
}

decode_profile() {
  local profile_path="$1"
  local prefix="$2"
  local plist="${tmpdir}/${prefix}.plist"
  local cert="${tmpdir}/${prefix}.cer"

  security cms -D -i "${profile_path}" > "${plist}"
  plutil -extract DeveloperCertificates.0 raw -o - "${plist}" | base64 --decode > "${cert}"

  local name uuid app_id serial fingerprint
  name="$(/usr/libexec/PlistBuddy -c 'Print Name' "${plist}")"
  uuid="$(/usr/libexec/PlistBuddy -c 'Print UUID' "${plist}")"
  app_id="$(/usr/libexec/PlistBuddy -c 'Print Entitlements:application-identifier' "${plist}")"
  serial="$(openssl x509 -inform DER -in "${cert}" -noout -serial | cut -d= -f2)"
  fingerprint="$(openssl x509 -inform DER -in "${cert}" -noout -fingerprint -sha1 | cut -d= -f2)"

  printf '%s\t%s\t%s\t%s\t%s\n' "${name}" "${uuid}" "${app_id}" "${serial}" "${fingerprint}"
}

gh_set_secret() {
  local name="$1"
  local value="$2"
  if [[ "${dry_run}" -eq 1 ]]; then
    printf 'dry-run: would set %s\n' "${name}"
    return
  fi
  printf '%s' "${value}" | gh secret set "${name}" --repo "${repo}" >/dev/null
  printf 'set %s\n' "${name}"
}

if [[ "${dry_run}" -eq 0 ]]; then
  gh auth status >/dev/null
fi

p12_serial="$(cert_serial_from_p12 "${p12}" "${p12_password}")"
p12_fingerprint="$(cert_fingerprint_from_p12 "${p12}" "${p12_password}")"

if [[ -z "${p12_serial}" ]]; then
  echo "Unable to decode P12 or extract certificate serial." >&2
  exit 1
fi

IFS=$'\t' read -r enterprise_name enterprise_uuid enterprise_app_id enterprise_serial enterprise_fingerprint \
  <<<"$(decode_profile "${profile_enterprise}" enterprise)"

expected_enterprise_app_id="${team_id}.com.xiuci.xcagi.mobile.enterprise"
expected_personal_app_id="${team_id}.com.xiuci.xcagi.mobile.personal"

[[ "${enterprise_app_id}" == "${expected_enterprise_app_id}" ]] || {
  echo "Enterprise profile bundle ID mismatch: ${enterprise_app_id}" >&2
  exit 1
}
[[ "${personal_app_id}" == "${expected_personal_app_id}" ]] || {
  echo "Personal profile bundle ID mismatch: ${personal_app_id}" >&2
  exit 1
}
[[ "${enterprise_serial}" == "${p12_serial}" ]] || {
  echo "Enterprise profile cert serial mismatch: ${enterprise_serial} != ${p12_serial}" >&2
  exit 1
}

printf 'P12 serial: %s\n' "${p12_serial}"
printf 'P12 fingerprint: %s\n' "${p12_fingerprint}"
printf 'Enterprise profile: %s (%s) [%s]\n' "${enterprise_name}" "${enterprise_uuid}" "${enterprise_app_id}"

if [[ -n "${profile_personal}" ]]; then
  IFS=$'\t' read -r personal_name personal_uuid personal_app_id personal_serial personal_fingerprint \
    <<<"$(decode_profile "${profile_personal}" personal)"

  [[ "${personal_app_id}" == "${expected_personal_app_id}" ]] || {
    echo "Personal profile bundle ID mismatch: ${personal_app_id}" >&2
    exit 1
  }
  [[ "${personal_serial}" == "${p12_serial}" ]] || {
    echo "Personal profile cert serial mismatch: ${personal_serial} != ${p12_serial}" >&2
    exit 1
  }

  printf 'Personal profile: %s (%s) [%s]\n' "${personal_name}" "${personal_uuid}" "${personal_app_id}"
fi

gh_set_secret "IOS_TEAM_ID" "${team_id}"
gh_set_secret "IOS_CERTIFICATE_P12_BASE64" "$(b64_file "${p12}")"
gh_set_secret "IOS_CERTIFICATE_PASSWORD" "${p12_password}"
gh_set_secret "IOS_PROVISION_PROFILE_ENTERPRISE_BASE64" "$(b64_file "${profile_enterprise}")"
if [[ -n "${profile_personal}" ]]; then
  gh_set_secret "IOS_PROVISION_PROFILE_PERSONAL_BASE64" "$(b64_file "${profile_personal}")"
fi
if [[ "${set_legacy_profile_secret}" -eq 1 ]]; then
  gh_set_secret "IOS_PROVISION_PROFILE_BASE64" "$(b64_file "${profile_enterprise}")"
fi
gh_set_secret "IOS_KEYCHAIN_PASSWORD" "${keychain_password}"
gh_set_secret "APP_STORE_CONNECT_API_KEY_ID" "${api_key_id}"
gh_set_secret "APP_STORE_CONNECT_API_ISSUER_ID" "${api_issuer_id}"
gh_set_secret "APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64" "$(b64_file "${api_key_p8}")"
