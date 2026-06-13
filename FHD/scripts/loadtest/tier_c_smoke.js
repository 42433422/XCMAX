/**
 * Tier C smoke — ramp to 200 VU on health + read-only APIs.
 * Usage: k6 run scripts/loadtest/tier_c_smoke.js
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, API_PATHS } from './config.js';

export const options = {
  scenarios: {
    tier_c_smoke: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 50 },
        { duration: '2m', target: 200 },
        { duration: '1m', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
  },
};

export default function () {
  const health = http.get(`${BASE_URL}${API_PATHS.health}`);
  check(health, { 'health 200': (r) => r.status === 200 });

  const live = http.get(`${BASE_URL}${API_PATHS.shipments}`);
  check(live, { 'liveness 200': (r) => r.status === 200 });

  const catalog = http.get(`${BASE_URL}${API_PATHS.products}`);
  check(catalog, { 'catalog ok': (r) => r.status === 200 || r.status === 401 });

  sleep(0.2);
}
