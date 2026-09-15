#!/bin/bash
# G10+G11: 1.0.0.4 启动后一键复验（health → digest 比对 → G7 业务复测）
# 用法: bash t5-post-ota-verify.sh
set -u
EV="$(cd "$(dirname "$0")" && pwd)"
BASE="http://127.0.0.1:17500"
LOG="$EV/t5-post-ota-verify.log"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "== T5 post-OTA verify start $(date '+%F %T') =="

echo "--- 1. health (expect 1.0.0.4 + 280225ac7) ---"
for i in $(seq 1 30); do
  H=$(curl --noproxy '*' -fsS "$BASE/api/health" 2>/dev/null) && break
  sleep 2
done
echo "$H" | python3 -c "
import json,sys
d=json.load(sys.stdin)
b=d.get('build',{})
print('status:',d.get('status'))
print('version:',d.get('version'))
print('git_sha:',(d.get('git_sha') or '')[:12])
print('release_id:',d.get('release_id'))
assert d.get('version')=='1.0.0.4', 'VERSION MISMATCH'
assert (d.get('git_sha') or '').startswith('280225ac'), 'SHA MISMATCH'
print('HEALTH OK')" && touch "$EV/t5-health-ok.marker" || { echo "HEALTH FAIL"; exit 1; }
echo "$H" > "$EV/t5-health-10004.json"

echo "--- 2. data digest 比对 (vs t5-pre-ota-digest.json) ---"
python3 "$EV/../macos-release-1.0.0.3/data_digest.py" "$EV/t5-post-ota-digest.json"
python3 - "$EV/t5-pre-ota-digest.json" "$EV/t5-post-ota-digest.json" <<'EOF'
import json,sys
pre=json.load(open(sys.argv[1])); post=json.load(open(sys.argv[2]))
keys=["xcagi.db.bytes","uploads.files","uploads.templates.files","mods.files","rows.templates","rows.users"]
print(f"{'key':32} {'pre':>14} {'post':>14} delta")
ok=True
for k in keys:
    p,q=pre.get(k),post.get(k)
    d=(q-p) if (isinstance(p,int) and isinstance(q,int)) else '?'
    print(f"{k:32} {str(p):>14} {str(q):>14} {d}")
    if isinstance(d,int) and d < 0: ok=False
print("DATA RETENTION:", "OK (no loss)" if ok else "LOSS DETECTED")
EOF

echo "--- 3. G7 业务复测 ---"
if [ -n "${XCAGI_TEST_USER:-}" ] && [ -n "${XCAGI_TEST_PASS:-}" ]; then
  python3 "$EV/g7_business_retest.py" --base "$BASE"
else
  echo "SKIP: XCAGI_TEST_USER/PASS 未设置，G7 业务复测稍后单独执行"
fi

echo "== T5 done $(date '+%F %T') =="
