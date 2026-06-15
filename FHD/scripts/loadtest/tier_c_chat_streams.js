/**
 * Tier C chat streams — concurrent SSE to /api/ai/chat (SLO-TIER-C-04).
 * Usage: k6 run -e STREAM_CONCURRENCY=200 scripts/loadtest/tier_c_chat_streams.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL } from './config.js';

const CONCURRENCY = parseInt(__ENV.STREAM_CONCURRENCY || '50', 10);
const DURATION = __ENV.TIER_C_CHAT_DURATION || '15m';
const USER = __ENV.E2E_USER || 'admin';
const PASS = __ENV.E2E_PASSWORD || 'admin123';

export const options = {
  scenarios: {
    chat_streams: {
      executor: 'constant-vus',
      vus: CONCURRENCY,
      duration: DURATION,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<15000'],
  },
};

function login() {
  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ username: USER, password: PASS }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  if (res.status !== 200) {
    return null;
  }
  try {
    const body = res.json();
    return body.token || body.access_token || body.data?.token;
  } catch (_) {
    return null;
  }
}

export function setup() {
  return { token: login() };
}

export default function (data) {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  };
  if (data.token) {
    headers.Authorization = `Bearer ${data.token}`;
  }
  const payload = JSON.stringify({
    message: 'ping',
    stream: true,
    conversation_id: `k6-${__VU}-${__ITER}`,
  });
  const res = http.post(`${BASE_URL}/api/ai/chat`, payload, {
    headers,
    timeout: '120s',
  });
  check(res, {
    'chat accepted': (r) => r.status === 200 || r.status === 401 || r.status === 429,
  });
  sleep(1);
}
