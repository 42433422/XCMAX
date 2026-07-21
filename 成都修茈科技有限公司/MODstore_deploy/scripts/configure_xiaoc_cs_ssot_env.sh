#!/usr/bin/env bash
# 在 CVM 上为 MODstore 写入小C SSOT 环境（FHD persy 检索）。
# 用法（root）：
#   bash scripts/configure_xiaoc_cs_ssot_env.sh
#   MODSTORE_ENV_FILE=/etc/xcmax/modstore.env FHD_ENV_FILE=/root/fhd-full.env \
#     bash scripts/configure_xiaoc_cs_ssot_env.sh
set -euo pipefail

MODSTORE_ENV_FILE="${MODSTORE_ENV_FILE:-/etc/xcmax/modstore.env}"
FHD_ENV_FILE="${FHD_ENV_FILE:-/root/fhd-full.env}"
FHD_API_BASE_URL="${FHD_API_BASE_URL:-http://127.0.0.1:5100}"
RESTART="${RESTART:-1}"

if [[ ! -f "$MODSTORE_ENV_FILE" ]]; then
  echo "ERROR: missing $MODSTORE_ENV_FILE" >&2
  exit 1
fi
if [[ ! -f "$FHD_ENV_FILE" ]]; then
  echo "ERROR: missing $FHD_ENV_FILE" >&2
  exit 1
fi

token="$(
  python3 - <<PY
from pathlib import Path
for line in Path("$FHD_ENV_FILE").read_text(encoding="utf-8", errors="replace").splitlines():
    if line.startswith("AUTONOMY_WEBHOOK_TOKEN="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"), end="")
        break
PY
)"
if [[ -z "$token" ]]; then
  echo "ERROR: AUTONOMY_WEBHOOK_TOKEN empty in $FHD_ENV_FILE" >&2
  exit 1
fi

backup="${MODSTORE_ENV_FILE}.bak.xiaoc-ssot.$(date +%Y%m%d%H%M%S)"
cp -a "$MODSTORE_ENV_FILE" "$backup"
echo "backup: $backup"

python3 - <<PY
from pathlib import Path

path = Path("$MODSTORE_ENV_FILE")
text = path.read_text(encoding="utf-8", errors="replace")
updates = {
    "FHD_API_BASE_URL": "$FHD_API_BASE_URL",
    "AUTONOMY_WEBHOOK_TOKEN": """$token""",
    "CS_SSOT_ENABLED": "1",
}
lines = text.splitlines()
keys_seen = set()
out = []
for line in lines:
    raw = line
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(raw)
        continue
    k, _ = line.split("=", 1)
    k = k.strip()
    if k in updates:
        out.append(f"{k}={updates[k]}")
        keys_seen.add(k)
    else:
        out.append(raw)
for k, v in updates.items():
    if k not in keys_seen:
        out.append(f"{k}={v}")
path.write_text(chr(10).join(out) + chr(10), encoding="utf-8")
print("updated keys:", ", ".join(sorted(updates)))
print("FHD_API_BASE_URL=$FHD_API_BASE_URL")
print("AUTONOMY_WEBHOOK_TOKEN_len=%d" % len("""$token"""))
PY

chmod 600 "$MODSTORE_ENV_FILE"

if [[ "$RESTART" == "1" ]]; then
  systemctl daemon-reload
  systemctl restart modstore.service
  systemctl is-active --quiet modstore.service
  echo "modstore.service: active"
fi

# smoke：本机 FHD cs-ssot retrieve
code="$(
  curl -sS -o /tmp/xiaoc-ssot-smoke.json -w '%{http_code}' -m 8 \
    -X POST "${FHD_API_BASE_URL%/}/api/ops/autonomy/cs-ssot/retrieve" \
    -H "X-Autonomy-Token: ${token}" \
    -H "Content-Type: application/json" \
    -d '{"query":"会员","top_k":2}' || true
)"
echo "fhd cs-ssot/retrieve http=$code"
python3 - <<'PY'
import json
from pathlib import Path
p = Path("/tmp/xiaoc-ssot-smoke.json")
if not p.exists():
    raise SystemExit("smoke body missing")
try:
    data = json.loads(p.read_text(encoding="utf-8"))
except Exception as exc:
    print("smoke parse fail", exc)
    raise SystemExit(1)
print("ok=", data.get("ok"), "dataset=", data.get("dataset_id"), "chunks=", len(data.get("chunks") or []))
PY

echo "done"
