#!/bin/bash
set -euo pipefail

TOOLKIT="/Users/a4243342/Desktop/XCMAX/FHD/XCAGI/resources/wechat-decrypt"
FHD="/Users/a4243342/Desktop/XCMAX/FHD"
PYTHON="${FHD}/.venv/bin/python"
SALTS_TSV="${TOOLKIT}/db_salts.tsv"

if ! pgrep -x WeChat >/dev/null; then
  echo "请先打开 /Applications/WeChat.app 并登录。"
  open -a "/Applications/WeChat.app" || true
  sleep 8
fi

echo "==> 1/4 收集加密库 salt"
cd "${TOOLKIT}"
python3 collect_wechat_db_salts.py
cp "${SALTS_TSV}" /tmp/wechat_db_salts.tsv

echo "==> 2/4 扫描内存密钥（sudo + Frida，会提示输入 Mac 密码）"
echo "    重要：请先在微信里打开 2～3 个群聊并滑动加载消息，再输入密码。"
"${PYTHON}" -m pip install frida-tools -q 2>/dev/null || true
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation 2>/dev/null || true
if sudo "${PYTHON}" find_all_keys_macos_py.py; then
  echo "Frida 扫描完成"
else
  echo "Frida 扫描未完全成功，尝试 C 扫描器..."
  PID=$(pgrep -x WeChat | head -1)
  [ -n "${PID}" ] && sudo env WECHAT_DB_SALTS_TSV=/tmp/wechat_db_salts.tsv ./find_all_keys_macos "${PID}" /tmp/wechat_db_salts.tsv || true
  sudo "${PYTHON}" match_memory_keys.py 2>/dev/null || true
fi

echo "==> 3/4 解密并写入配置"
cd "${FHD}"
export PYTHONPATH="${FHD}:${TOOLKIT}"
"${PYTHON}" <<'PY'
from app.services.wechat_decrypt_autoconfig import auto_configure_wechat_decrypt, prepare_wechat_message_db_for_read
from app.services.wechat_group_customer_bridge import sync_group_messages

cfg = auto_configure_wechat_decrypt(force_key_scan=False)
print("configure success:", cfg.get("success"), "stale:", cfg.get("message_db_stale"))
prep = prepare_wechat_message_db_for_read(force_decrypt=True, retry_key_scan=False)
print("message stale:", prep.get("stale"), "path:", prep.get("message_db_path"))
sync = sync_group_messages(group_limit=50, message_limit=80)
print("sync:", sync)
PY

echo "==> 4/4 完成。若 sync 仍失败，请确认 all_keys.json 含 message/message_0.db 且解密库时间为今天。"
