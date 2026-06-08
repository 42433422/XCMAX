#!/bin/bash
set -e
echo "=== 1. FunASR direct (api -> funasr) ==="
docker cp /tmp/test_funasr_ws.py modstore_deploy-api-1:/tmp/test_funasr_ws.py
docker exec -e FUNASR_HOST=funasr modstore_deploy-api-1 python /tmp/test_funasr_ws.py

echo "=== 2. ASR proxy health (no token) ==="
docker cp /tmp/test_asr_proxy_ws.py modstore_deploy-api-1:/tmp/test_asr_proxy_ws.py
docker exec modstore_deploy-api-1 python /tmp/test_asr_proxy_ws.py || true

echo "=== 3. ASR full chain (JWT + PCM + end) ==="
docker cp /tmp/test_asr_full.py modstore_deploy-api-1:/tmp/test_asr_full.py
docker exec -w /app modstore_deploy-api-1 python /tmp/test_asr_full.py

echo "=== 4. TTS edge endpoint latency ==="
docker exec modstore_deploy-api-1 python -c "
import time, urllib.request, json
body = json.dumps({'text': '冒烟测试', 'voice': 'zh-CN-XiaoxiaoNeural', 'rate': 1.0}).encode()
req = urllib.request.Request('http://127.0.0.1:8765/api/workbench/tts/edge', data=body, headers={'Content-Type':'application/json'}, method='POST')
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        print('TTS OK bytes=%d latency_ms=%d' % (len(data), int((time.time()-t0)*1000)))
except Exception as e:
    print('TTS FAIL:', e)
"

echo "=== 5. Deployed frontend bundle ==="
docker exec modstore_deploy-market-1 sh -c 'grep -o "index-[^\"]*" /usr/share/nginx/html/market/index.html; test -f /usr/share/nginx/html/market/assets/index-0o-4boUO.js && echo bundle_exists'

echo "=== 6. FunASR recent logs ==="
docker logs modstore_deploy-funasr-1 --tail 8 2>&1

echo "=== SMOKE DONE ==="
