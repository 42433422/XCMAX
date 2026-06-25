#!/usr/bin/env bash
set -euo pipefail

# 用华为 AppGallery 生产签名材料(来自 GitHub secrets / 环境变量)配置 HarmonyOS 签名:
# 把 .p12/.cer/.p7b 解码进 mobile-harmony/signing/(已 gitignore),并把 build-profile.json5
# 的 signingConfigs[release] + products[default].signingConfig 补成 "release"。
#
# 对标 iOS(release-ios.yml)与 Android(release-android.yml)的"secret 注入签名":
#   - 配齐签名 secret  → 产出**已签名** HAP,可上 AppGallery / 真机安装
#   - 未配 secret      → **no-op 退出 0**,不动 build-profile.json5,离线 unsigned smoke 构建不受影响
#     (此时 release 构建会被 build-hap.sh 的"拒绝未签名 HAP"挡下,符合预期)
#
# 必填环境变量:
#   HARMONY_SIGN_STORE_P12_BASE64   keystore .p12 的 base64
#   HARMONY_SIGN_CERT_BASE64        签名证书 .cer 的 base64
#   HARMONY_SIGN_PROFILE_BASE64     Provision Profile .p7b 的 base64
#   HARMONY_SIGN_STORE_PASSWORD     storePassword(从本地可用的 DevEco build-profile.json5 原样复制;通常是 DevEco 加密串)
#   HARMONY_SIGN_KEY_PASSWORD       keyPassword(同上)
#   HARMONY_SIGN_KEY_ALIAS          key 别名
# 选填:
#   HARMONY_SIGN_ALG                signAlg(默认 SHA256withECDSA)
#
# ⚠️ 本脚本会就地修改 build-profile.json5(写入签名引用);CI runner 为临时环境无碍。
#    本地运行后请勿把改动连同密码提交,用 `git checkout -- build-profile.json5` 还原。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROFILE="${MODULE_ROOT}/build-profile.json5"
SIGN_DIR="${MODULE_ROOT}/signing"

if [[ -z "${HARMONY_SIGN_STORE_P12_BASE64:-}" || -z "${HARMONY_SIGN_CERT_BASE64:-}" || -z "${HARMONY_SIGN_PROFILE_BASE64:-}" ]]; then
  echo "::warning::HarmonyOS 签名材料 secret 未配置(HARMONY_SIGN_STORE_P12_BASE64 / _CERT_BASE64 / _PROFILE_BASE64),跳过签名配置。release 构建会因拒绝未签名 HAP 而失败——请配齐签名 secret,或给发版 workflow 传入已签名的 --harmony-artifact。"
  exit 0
fi

missing=()
for v in HARMONY_SIGN_STORE_PASSWORD HARMONY_SIGN_KEY_PASSWORD HARMONY_SIGN_KEY_ALIAS; do
  [[ -z "${!v:-}" ]] && missing+=("$v")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "::error::HarmonyOS 签名材料已给但缺少: ${missing[*]}" >&2
  exit 1
fi

PY="python3"
command -v python3 >/dev/null 2>&1 || PY="python"
command -v "$PY" >/dev/null 2>&1 || { echo "::error::需要 python3 来 patch build-profile.json5" >&2; exit 127; }

mkdir -p "${SIGN_DIR}"
echo "${HARMONY_SIGN_STORE_P12_BASE64}" | base64 -d > "${SIGN_DIR}/release.p12"
echo "${HARMONY_SIGN_CERT_BASE64}"      | base64 -d > "${SIGN_DIR}/release.cer"
echo "${HARMONY_SIGN_PROFILE_BASE64}"   | base64 -d > "${SIGN_DIR}/release.p7b"
chmod 600 "${SIGN_DIR}"/release.* 2>/dev/null || true

"$PY" - "$PROFILE" <<'PY'
import json, os, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)

cfg = {
    "name": "release",
    "type": "HarmonyOS",
    "material": {
        "certpath": "signing/release.cer",
        "storePassword": os.environ["HARMONY_SIGN_STORE_PASSWORD"],
        "keyAlias": os.environ["HARMONY_SIGN_KEY_ALIAS"],
        "keyPassword": os.environ["HARMONY_SIGN_KEY_PASSWORD"],
        "profile": "signing/release.p7b",
        "signAlg": os.environ.get("HARMONY_SIGN_ALG", "SHA256withECDSA"),
        "storeFile": "signing/release.p12",
    },
}

app = data.setdefault("app", {})
app["signingConfigs"] = [c for c in app.get("signingConfigs", []) if c.get("name") != "release"] + [cfg]
for product in app.get("products", []):
    if product.get("name") == "default":
        product["signingConfig"] = "release"

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(f"patched {path}: signingConfigs[release] + products[default].signingConfig=release")
PY

echo "HarmonyOS 生产签名已就绪:material 解码至 ${SIGN_DIR},build-profile.json5 已引用 release 配置。"
