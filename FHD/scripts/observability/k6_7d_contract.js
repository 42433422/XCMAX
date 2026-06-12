/**
 * k6 7-day contract traffic — health + login + chat/stream for M0 SLO metrics.
 * Deploy: bash FHD/scripts/observability/sync_k6_configmap.sh --apply
 *         kubectl apply -f FHD/k8s/monitoring/k6-7day-job.yaml
 */
import http from 'k6/http';
import { check, sleep } from 'k6';

// Staging Job 历史曾用 BASE_URL；脚本统一兼容两种 env。
const BASE =
  __ENV.XCAGI_BASE_URL || __ENV.BASE_URL || 'http://127.0.0.1:5000';
const USER = __ENV.E2E_USER || 'admin';
const PASS = __ENV.E2E_PASSWORD || 'admin123';

export const options = {
  scenarios: {
    contract_7d: {
      executor: 'constant-arrival-rate',
      rate: 30,
      timeUnit: '1m',
      duration: __ENV.K6_DURATION || '168h',
      preAllocatedVUs: 5,
      maxVUs: 20,
      startTime: '0s',
    },
    tier_c_ramp: {
      executor: 'ramping-arrival-rate',
      startRate: 10,
      timeUnit: '1m',
      preAllocatedVUs: 20,
      maxVUs: 200,
      stages: [
        { duration: '24h', target: 60 },
        { duration: '24h', target: 120 },
        { duration: '24h', target: 240 },
        { duration: '24h', target: 480 },
        { duration: '24h', target: 600 },
        { duration: '24h', target: 600 },
      ],
      startTime: '1h',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<15000'],
  },
};

function csrfFrom(res) {
  return (
    res.cookies.csrf_token?.[0]?.value ||
    res.cookies['csrf-token']?.[0]?.value ||
    ''
  );
}

function jsonHeaders(csrf) {
  return {
    'Content-Type': 'application/json',
    ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
  };
}

export default function () {
  const health = http.get(`${BASE}/api/health`, { tags: { name: 'health' } });
  check(health, { 'health 200': (r) => r.status === 200 });

  const csrf = csrfFrom(health);
  const headers = jsonHeaders(csrf);

  const login = http.post(
    `${BASE}/api/auth/login`,
    JSON.stringify({ username: USER, password: PASS, account_kind: 'personal' }),
    { headers, tags: { name: 'login' } }
  );
  check(login, { 'login ok': (r) => r.status === 200 });

  const chat = http.post(
    `${BASE}/api/ai/chat/stream`,
    JSON.stringify({ message: 'k6 contract probe' }),
    { headers, timeout: '60s', tags: { name: 'chat_stream' } }
  );
  check(chat, { 'chat stream ok': (r) => r.status === 200 });

  sleep(1);
}
