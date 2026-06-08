import http from 'k6/http';
import ws from 'k6/ws';
import { check, group, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE_URL = (__ENV.BASE_URL || 'http://127.0.0.1:4173').replace(/\/$/, '');
const WS_URL = (__ENV.WS_URL || BASE_URL.replace(/^http/, 'ws')).replace(/\/$/, '');
const STAGE = __ENV.K6_STAGE || 'smoke';
const TEST_EMAIL = __ENV.TEST_EMAIL || '';
const TEST_PASSWORD = __ENV.TEST_PASSWORD || '';
const ENABLE_LLM = (__ENV.ENABLE_LLM || 'false').toLowerCase() === 'true';
const ENABLE_RAG = (__ENV.ENABLE_RAG || 'false').toLowerCase() === 'true';

export const businessErrors = new Counter('modstore_business_errors');
export const wsConnectLatency = new Trend('modstore_ws_connect_latency');

function scenarioOptions() {
  if (STAGE === 'step') {
    return {
      stages: [
        { duration: '1m', target: 10 },
        { duration: '2m', target: 30 },
        { duration: '1m', target: 0 },
      ],
    };
  }
  if (STAGE === 'soak') {
    return {
      stages: [
        { duration: '2m', target: 20 },
        { duration: '20m', target: 20 },
        { duration: '2m', target: 0 },
      ],
    };
  }
  if (STAGE === 'spike') {
    return {
      stages: [
        { duration: '30s', target: 10 },
        { duration: '30s', target: 80 },
        { duration: '1m', target: 80 },
        { duration: '30s', target: 0 },
      ],
    };
  }
  return {
    vus: 2,
    duration: '1m',
  };
}

const thresholds = {
  http_req_failed: ['rate<0.02'],
  http_req_duration: ['p(95)<1000', 'p(99)<2500'],
  modstore_business_errors: ['count<5'],
};

if (TEST_EMAIL && TEST_PASSWORD) {
  thresholds.modstore_ws_connect_latency = ['p(95)<1000'];
}

export const options = {
  ...scenarioOptions(),
  thresholds,
};

function jsonHeaders(token) {
  const headers = {
    'Content-Type': 'application/json',
    'X-Request-Id': `k6-${__VU}-${__ITER}-${Date.now()}`,
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return { headers };
}

function record(ok, name) {
  if (!ok) {
    businessErrors.add(1, { check: name });
  }
}

function jsonValue(response, selector) {
  try {
    return response.json(selector);
  } catch {
    return '';
  }
}

function login() {
  if (!TEST_EMAIL || !TEST_PASSWORD) {
    return '';
  }
  const res = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD }),
    jsonHeaders(),
  );
  const ok = check(res, {
    'login status is 200': (r) => r.status === 200,
    'login has token': (r) => Boolean(jsonValue(r, 'access_token') || jsonValue(r, 'token')),
  });
  record(ok, 'login');
  return jsonValue(res, 'access_token') || jsonValue(res, 'token') || '';
}

function getJson(path, token, expectedStatuses = [200]) {
  const res = http.get(`${BASE_URL}${path}`, jsonHeaders(token));
  const ok = check(res, {
    [`GET ${path} expected status`]: (r) => expectedStatuses.includes(r.status),
  });
  record(ok, path);
  return res;
}

function exerciseWebSocket(token) {
  if (!token) {
    return;
  }
  const started = Date.now();
  const response = ws.connect(`${WS_URL}/api/realtime/ws?token=${encodeURIComponent(token)}`, {}, (socket) => {
    socket.on('open', () => {
      wsConnectLatency.add(Date.now() - started);
      socket.setTimeout(() => socket.close(), 1000);
    });
    socket.on('error', () => {
      businessErrors.add(1, { check: 'websocket' });
    });
  });
  const ok = check(response, {
    'websocket switched protocols': (r) => r && r.status === 101,
  });
  record(ok, 'websocket');
}

export default function () {
  let token = '';

  group('auth', () => {
    token = login();
    if (token) {
      getJson('/api/auth/me', token);
    }
  });

  group('market', () => {
    getJson('/api/health');
    getJson('/health/live');
    getJson('/api/market/catalog');
    getJson('/api/market/facets');
    getJson('/v1/packages', token, [200, 404]);
  });

  group('payment-wallet', () => {
    getJson('/api/payment/plans', token, [200, 401, 403, 502]);
    getJson('/api/wallet/balance', token, [200, 401, 403, 502]);
    getJson('/api/payment/orders', token, [200, 401, 403, 502, 404]);
  });

  group('knowledge-llm', () => {
    if (ENABLE_RAG) {
      getJson('/api/knowledge/documents', token, [200, 401, 403, 404]);
      http.post(`${BASE_URL}/api/knowledge/search`, JSON.stringify({ query: 'modstore', limit: 3 }), jsonHeaders(token));
    }
    if (ENABLE_LLM) {
      getJson('/api/llm/status', token, [200, 401, 403, 404, 502]);
    }
  });

  group('realtime', () => {
    exerciseWebSocket(token);
  });

  sleep(Math.random() * 2 + 1);
}
