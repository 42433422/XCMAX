/**
 * Tier C sustained — constant 1000 RPS on health + read-only paths (SLO-TIER-C-01).
 * Usage: k6 run scripts/loadtest/tier_c_sustained.js -e BASE_URL=https://staging.example
 */
import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, API_PATHS } from './config.js';

const RATE = parseInt(__ENV.TIER_C_RPS || '1000', 10);
const DURATION = __ENV.TIER_C_DURATION || '10m';

export const options = {
  scenarios: {
    tier_c_sustained: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.min(RATE, 500),
      maxVUs: Math.min(RATE * 2, 1000),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    http_req_duration: ['p(95)<500'],
  },
};

const paths = [API_PATHS.health, API_PATHS.shipments, API_PATHS.products];

export default function () {
  const path = paths[Math.floor(Math.random() * paths.length)];
  const res = http.get(`${BASE_URL}${path}`);
  check(res, { 'status ok': (r) => r.status < 500 });
}
