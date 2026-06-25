#!/usr/bin/env bash
# 鸿蒙发版员 · 全自动一条龙(hvigor 官方一体化签名 → AGC 上传 + 提交审核)。
#
# 签名:hvigor SignHap + SignApp(.app 级签名,AGC 唯一认的方式)。密码经工具链固定
#   material 加密成密文喂给 hvigor(见 ~/XCMAX-runtime/harmony/signing/encrypt-pwd.js)。
# 质量门:verify-app 验 .app 文件本身不过则中止,绝不推坏包(工程校验,非人工审批)。
# 密钥/密码:仓库外 ~/XCMAX-runtime/harmony/signing/agc-api.env
#   AGC_CLIENT_ID / AGC_CLIENT_SECRET / AGC_APP_ID / HARMONY_KEY_PWD
# 路径无关:PROJ 由脚本自身位置推导,任何 checkout 都能跑。
#
# 用法:release-harmony.sh [--version-code N] [--no-submit]
set -euo pipefail

SUBMIT=1; VCODE=""
while [[ $# -gt 0 ]]; do case "$1" in
  --version-code) VCODE="${2:-}"; shift 2;;
  --no-submit) SUBMIT=0; shift;;
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "未知参数: $1" >&2; exit 2;;
esac; done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ="$(cd "${SCRIPT_DIR}/.." && pwd)"                      # FHD/mobile-harmony(路径无关)
SIGN="${HOME}/XCMAX-runtime/harmony/signing"
PLUGIN="${HOME}/XCMAX-runtime/harmony/command-line-tools/hvigor/hvigor-ohos-plugin"
LIB="${HOME}/XCMAX-runtime/harmony/command-line-tools/sdk/default/openharmony/toolchains/lib"
export PATH="${HOME}/XCMAX-runtime/harmony/bin:${PATH}"
[[ -f "${SIGN}/agc-api.env" ]] && set -a && . "${SIGN}/agc-api.env" && set +a
: "${HARMONY_KEY_PWD:?缺 HARMONY_KEY_PWD(放 ${SIGN}/agc-api.env)}"
for f in "${SIGN}/xcagi-release.p12" "${SIGN}/xcagi-release.cer" "${SIGN}/xcagi-release.p7b" "${SIGN}/encrypt-pwd.js"; do
  [[ -f "$f" ]] || { echo "缺签名材料: $f" >&2; exit 1; }
done

cd "$PROJ"
VNAME="$(python3 -c "import json,re;s=open('AppScope/app.json5').read();print(re.search(r'\"versionName\"\s*:\s*\"([^\"]+)\"',s).group(1))")"
OUT="${SIGN}/XCAGI-Enterprise-Harmony-${VNAME}.app"
APPJSON="AppScope/app.json5"
RESTORE_APPJSON=0

echo "========== 鸿蒙发版 v${VNAME} =========="

# 可选:覆盖 versionCode(AGC 要求每次上传严格递增;定时发版员传 git 派生的单调值)
if [[ -n "$VCODE" ]]; then
  cp "$APPJSON" "${APPJSON}.bak"; RESTORE_APPJSON=1
  python3 - "$APPJSON" "$VCODE" <<'PY'
import sys,re
p,vc=sys.argv[1],sys.argv[2]
s=open(p).read()
s=re.sub(r'("versionCode"\s*:\s*)\d+', r'\g<1>'+vc, s, count=1)
open(p,'w').write(s)
PY
  echo "versionCode → $VCODE"
fi
cleanup(){ [[ "$RESTORE_APPJSON" == 1 ]] && mv -f "${APPJSON}.bak" "$APPJSON" 2>/dev/null || true; rm -rf "${TMPD:-}"; }
trap cleanup EXIT

echo "--- [1] material + 证书链 + 密码密文 ---"
[[ -d "${SIGN}/material/fd" ]] || cp -R "${PLUGIN}/res/material" "${SIGN}/material"
python3 - "${SIGN}/xcagi-release.cer" "${SIGN}/xcagi-release-chain.cer" <<'PY'
import sys
d=open(sys.argv[1]).read()
b=[x[x.index('-----BEGIN CERTIFICATE-----'):]+'-----END CERTIFICATE-----\n' for x in d.split('-----END CERTIFICATE-----') if 'BEGIN CERTIFICATE' in x]
open(sys.argv[2],'w').write(''.join(reversed(b)))
PY
CIPHER="$(node "${SIGN}/encrypt-pwd.js" "$SIGN" "$HARMONY_KEY_PWD" | grep '^CIPHER=' | cut -d= -f2)"
[[ -n "$CIPHER" ]] || { echo "密码加密失败" >&2; exit 1; }

echo "--- [2] hvigor 一体化签名构建(SignHap + SignApp)---"
export HARMONY_PWD_CIPHER="$CIPHER"
hvigor --no-daemon clean >/dev/null 2>&1 || true
hvigor --no-daemon assembleApp -p product=default -p buildMode=release 2>&1 | grep -iE "SignHap|SignApp|BUILD|ERROR" | tail -5
unset HARMONY_PWD_CIPHER
SIGNED="$(find build/outputs -name '*-signed.app' | head -1)"
[[ -f "$SIGNED" ]] || { echo "未产出 signed .app(签名失败?)" >&2; exit 1; }

echo "--- [3] 质量门:验签 .app 文件本身 ---"
if ! java -jar "${LIB}/hap-sign-tool.jar" verify-app -inFile "$PROJ/$SIGNED" \
     -outCertChain /tmp/_rh_vc.cer -outProfile /tmp/_rh_vp.p7b 2>&1 | grep -q "verify-app success"; then
  echo "❌ .app 验签未通过,中止发版(不推坏包)" >&2; exit 1
fi
cp -f "$PROJ/$SIGNED" "$OUT"
echo "✅ 官方签名上架包: $OUT"

echo "--- [4] AGC 上传 + 提交 ---"
PUB_ARGS=(); [[ "$SUBMIT" == 0 ]] && PUB_ARGS+=(--no-submit)
python3 "${PROJ}/scripts/publish-agc-harmony.py" --app "$OUT" "${PUB_ARGS[@]}"
echo "========== 发版流程结束 v${VNAME} =========="
