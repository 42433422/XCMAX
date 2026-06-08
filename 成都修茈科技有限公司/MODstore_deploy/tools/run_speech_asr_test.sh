#!/bin/bash
set -e
docker cp /tmp/test_asr_with_speech.py modstore_deploy-api-1:/tmp/test_asr_with_speech.py
echo "=== deps ==="
docker exec modstore_deploy-api-1 sh -c 'which ffmpeg || echo NO_FFMPEG; python -c "import edge_tts; print(\"edge_tts ok\")"'
echo "=== run speech ASR test ==="
docker exec -w /app modstore_deploy-api-1 python /tmp/test_asr_with_speech.py
echo "=== public WSS (optional) ==="
docker exec -w /app -e ASR_WS_URL='wss://xiu-ci.com/api/asr/funasr' modstore_deploy-api-1 python /tmp/test_asr_with_speech.py || true
