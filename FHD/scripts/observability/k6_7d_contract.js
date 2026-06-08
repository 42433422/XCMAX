/**
 * k6 7-day contract traffic — covers health, login, AI chat for SLO metrics.
 * Deploy as K8s CronJob or long-running Job (see k8s/monitoring/k6-7day-job.yaml).
 */
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.XCAGI_BASE_URL || 'http://127.0.0.1:5000';
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
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    http_req_duration: ['p(95)<1500'],
  },
};

function csrfHeaders() {
  const h = http.get(`${BASE}/api/health`);
  const token = h.cookies.csrf_token?.[0]?.value || h.cookies['csrf-token']?.[0]?.value || '';
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'X-CSRF-Token': token } : {}),
  };
}

export default function () {
  const health = http.get(`${BASE}/api/health`);
  check(health, { 'health 200': (r) => r.status === 200 });

  const headers = csrfHeaders();
  const login = http.post(
    `${BASE}/api/auth/login`,
    JSON.stringify({ username: USER, password: PASS, account_kind: 'personal' }),
    { headers }
  );
  check(login, { 'login < 500': (r) => r.status < 500 });

  const chat = http.post(
    `${BASE}/api/ai/chat`,
    JSON.stringify({ message: 'k6 contract probe' }),
    { headers }
  );
  check(chat, { 'chat < 500': (r) => r.status < 500 });

  sleep(1);
}
