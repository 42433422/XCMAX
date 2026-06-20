#!/usr/bin/env bash
# ============================================================================
# XCAGI Android Release Keystore 生成脚本
# 用法:在 FHD/mobile-android 目录下运行  bash signing/generate-keystore.sh
# 产出:signing/xcagi-release.jks + keystore.properties(均已在 .gitignore)
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
KEYSTORE_PATH="${SCRIPT_DIR}/xcagi-release.jks"
PROPS_PATH="${PROJECT_DIR}/keystore.properties"
ALIAS="xcagi_release"
VALIDITY=36500  # 100 年

# --- 前置检查 ---
if ! command -v keytool >/dev/null 2>&1; then
  echo "错误:未找到 keytool,请先安装 JDK 17+" >&2
  exit 1
fi

if [[ -f "${KEYSTORE_PATH}" ]]; then
  echo "错误:keystore 已存在:${KEYSTORE_PATH}" >&2
  echo "如需重新生成,请先备份并删除该文件(注意:换 keystore 后旧 APK 无法升级)" >&2
  exit 1
fi

# --- 交互式输入密码(不回显) ---
echo "即将为 XCAGI Android 生成 release 签名 keystore"
echo "请妥善保管密码,丢失后无法为同一 applicationId 发布更新包"
echo

read -s -p "请输入 keystore 密码(storePassword,至少 6 位): " STORE_PASS
echo
if [[ ${#STORE_PASS} -lt 6 ]]; then
  echo "错误:密码至少 6 位" >&2
  exit 1
fi

read -s -p "请再次输入 keystore 密码(确认): " STORE_PASS_CONFIRM
echo
if [[ "${STORE_PASS}" != "${STORE_PASS_CONFIRM}" ]]; then
  echo "错误:两次输入的密码不一致" >&2
  exit 1
fi

read -s -p "请输入 key 密码(keyPassword,直接回车则与 storePassword 相同): " KEY_PASS
echo
KEY_PASS="${KEY_PASS:-${STORE_PASS}}"
if [[ ${#KEY_PASS} -lt 6 ]]; then
  echo "错误:key 密码至少 6 位" >&2
  exit 1
fi

# --- 生成 keystore ---
echo
echo "正在生成 keystore(RSA 4096,有效期 100 年)..."
keytool -genkeypair \
  -alias "${ALIAS}" \
  -keyalg RSA \
  -keysize 4096 \
  -validity "${VALIDITY}" \
  -keystore "${KEYSTORE_PATH}" \
  -storepass "${STORE_PASS}" \
  -keypass "${KEY_PASS}" \
  -dname "CN=XCAGI, OU=Mobile, O=成都修茈科技有限公司, L=成都, ST=四川, C=CN"

# --- 生成 keystore.properties(从模板,填入实际密码) ---
cat > "${PROPS_PATH}" <<EOF
storeFile=signing/xcagi-release.jks
storePassword=${STORE_PASS}
keyAlias=${ALIAS}
keyPassword=${KEY_PASS}
EOF
chmod 600 "${PROPS_PATH}"

# --- 完成 ---
echo
echo "✅ keystore 生成成功"
echo "   密钥库:${KEYSTORE_PATH}"
echo "   配置文件:${PROPS_PATH}"
echo "   别名:${ALIAS}"
echo
echo "⚠️  重要后续步骤:"
echo "   1. 立即备份 ${KEYSTORE_PATH} 到密码管理器 / 离线保险柜"
echo "      丢失后无法为同一 applicationId 发布更新包"
echo "   2. 两个文件均已在 .gitignore 中,不会被提交到 Git"
echo "   3. 如需 CI 自动签名,将以下 4 个值配置到 GitHub Secrets:"
echo "      - ANDROID_KEYSTORE_BASE64:运行下面的命令获取"
echo "        base64 -i ${KEYSTORE_PATH} | tr -d '\\n'"
echo "      - ANDROID_KEYSTORE_PASSWORD:${STORE_PASS:0:1}****(你的 storePassword)"
echo "      - ANDROID_KEY_ALIAS:${ALIAS}"
echo "      - ANDROID_KEY_PASSWORD:你的 keyPassword"
echo "   4. 本地验证签名构建:"
echo "        cd ${PROJECT_DIR} && ./gradlew assembleEnterpriseRelease"
