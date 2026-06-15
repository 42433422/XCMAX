#!/usr/bin/env bash
# 企业开发：市场走公网 https://xiu-ci.com（方案 B，无需本地 MODstore :8788）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export XCAGI_USE_REMOTE_MARKET=1
export XCAGI_MARKET_BASE_URL="${XCAGI_MARKET_BASE_URL:-https://xiu-ci.com}"
# 公网市场 LLM 首包实测常 12–18s，默认 20s 易误报超时
export XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC="${XCAGI_CHAT_STREAM_FIRST_TOKEN_TIMEOUT_SEC:-60}"
exec "${SCRIPT_DIR}/start-enterprise-dev.sh"
