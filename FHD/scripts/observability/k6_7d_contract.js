/**
 * k6 contract traffic: real login, stream and original durable turn readback.
 * Use a dedicated, read-only acceptance account; never replay a chat POST.
 * XCAGI_SOAK_DURATION defaults to 168h; shorter runs retain their actual duration.
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

// Staging Job 历史曾用 BASE_URL；脚本统一兼容两种 env。
const BASE =
  __ENV.XCAGI_BASE_URL || __ENV.BASE_URL || 'http://127.0.0.1:5000';
const USER = __ENV.E2E_USER || '';
const PASS = __ENV.E2E_PASSWORD || '';
const SOURCE_SHA = __ENV.SOURCE_SHA || __ENV.GITHUB_SHA || '';
const verifiedTurns = new Counter('chat_turns_verified');

export const options = {
  tags: { source_sha: SOURCE_SHA, environment: __ENV.XCAGI_ENVIRONMENT || 'staging' },
  scenarios: {
    contract_7d: {
      executor: 'constant-arrival-rate',
      rate: 30,
      timeUnit: '1m',
      duration: __ENV.XCAGI_SOAK_DURATION || '168h',
      preAllocatedVUs: 5,
      maxVUs: 20,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<15000'],
    checks: ['rate==1'],
    iterations: ['count>0'],
    dropped_iterations: ['count==0'],
    chat_turns_verified: ['count>0'],
  },
};

export function setup() {
  if (!USER || !PASS || !/^[0-9a-f]{40}$/.test(SOURCE_SHA)) {
    throw new Error('Set E2E_USER, E2E_PASSWORD and the tested SOURCE_SHA explicitly');
  }
  const workload = exec.test.options.scenarios.contract_7d;
  if (!workload || workload.executor !== 'constant-arrival-rate' || workload.rate !== 30
      || !['1m', '1m0s'].includes(workload.timeUnit)) {
    throw new Error('The native k6 workload was overridden; use XCAGI_SOAK_DURATION to set its duration');
  }
  return { run_id: `k6-${Date.now()}-${Math.random().toString(36).slice(2)}` };
}

function jsonHeaders() {
  const cookies = http.cookieJar().cookiesForURL(BASE);
  const csrf = (cookies.csrf_token || cookies['csrf-token'] || [])[0];
  const h = { 'Content-Type': 'application/json' };
  if (csrf) h['X-CSRF-Token'] = csrf;
  return h;
}

function jsonBody(response) {
  try { return response.json() || {}; } catch (_) { return {}; }
}

export function handleSummary(data) {
  const workload = exec.test.options.scenarios.contract_7d || {};
  const summary = JSON.stringify({
    ...data,
    source_sha: SOURCE_SHA,
    environment: __ENV.XCAGI_ENVIRONMENT || 'staging',
    test_profile: 'chat-durable-turn/v1',
    workload,
    completed_at: new Date().toISOString(),
    duration: workload.duration || '',
    scope: 'synthetic acceptance account; real login, stream and durable turn readback',
    business_reconciliation: false,
  }, null, 2);
  return { [__ENV.K6_SUMMARY_PATH || 'k6-7d-summary.json']: summary, stdout: summary + '\n' };
}

export default function (data) {
  const health = http.get(`${BASE}/api/health`, { timeout: '15s', tags: { name: 'health' } });
  if (!check(health, {
    'healthy tested build': (r) => r.status === 200
      && jsonBody(r).status === 'healthy' && jsonBody(r).git_sha === SOURCE_SHA,
  })) return;

  const login = http.post(
    `${BASE}/api/auth/login`,
    JSON.stringify({ username: USER, password: PASS, account_kind: __ENV.E2E_ACCOUNT_KIND || 'enterprise' }),
    { headers: jsonHeaders(), timeout: '15s', tags: { name: 'login' } }
  );
  if (!check(login, { 'login ok': (r) => r.status === 200 && jsonBody(r).success === true })) return;

  // Keep the original identity through transport failure. Never send a second POST.
  const sessionId = `${data.run_id}-${__VU}`;
  const turnId = `${sessionId}-${__ITER}`;
  const chat = http.post(
    `${BASE}/api/ai/chat/stream`,
    JSON.stringify({
      message: '请仅回复：运行探测完成。不要调用工具或修改任何业务数据。',
      context: { session_id: sessionId, conversation_id: sessionId, turn_id: turnId },
    }),
    { headers: jsonHeaders(), timeout: '15s', tags: { name: 'chat_stream' } }
  );
  check(chat, {
    'chat stream HTTP contract': (r) => r.status === 200
      && String(r.headers['Content-Type'] || '').includes('text/event-stream'),
  });
  const original = http.get(
    `${BASE}/api/conversations/${encodeURIComponent(sessionId)}?turn_id=${encodeURIComponent(turnId)}`,
    { headers: jsonHeaders(), timeout: '15s', tags: { name: 'chat_readback' } }
  );
  const history = jsonBody(original);
  const receipt = history.turn_receipt || {};
  const verified = check(original, {
    'original durable turn completed': (r) => r.status === 200
      && history.success === true && history.durable === true && history.id === sessionId
      && receipt.turn_id === turnId && receipt.durable === true
      && receipt.status === 'completed' && receipt.requires_reconciliation === false,
  });
  verifiedTurns.add(verified ? 1 : 0);

  sleep(1);
}
