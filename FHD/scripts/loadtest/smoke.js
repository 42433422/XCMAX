import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, API_PATHS, THRESHOLDS } from './config.js';

export const options = {
  vus: 5,
  duration: '30s',
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
  thresholds: {
    http_req_duration: [`p(95)<${THRESHOLDS.p95}`, `p(99)<${THRESHOLDS.p99}`],
    http_req_failed: ['rate==0'],
    checks: ['rate==1'],
    http_reqs: ['count>=20'],
  },
};

export function handleSummary(data) {
  return {
    'performance-results/k6-summary.json': JSON.stringify({
      ...data,
      source_sha: __ENV.GITHUB_SHA || __ENV.SOURCE_SHA || null,
      scope: 'real HTTP health/ping regression; business datasets measured separately',
      budgets_ms: { p95: THRESHOLDS.p95, p99: THRESHOLDS.p99 },
      workload: { vus: options.vus, duration: options.duration },
    }, null, 2),
  };
}

export default function () {
  for (const path of [API_PATHS.health, '/api/ping']) {
    const response = http.get(`${BASE_URL}${path}`, { tags: { endpoint: path } });
    check(response, { 'HTTP 200 JSON': (r) => r.status === 200 && String(r.headers['Content-Type']).includes('application/json') });
    sleep(1);
  }
}
