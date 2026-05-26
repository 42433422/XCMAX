import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, API_PATHS } from './config.js';

export const options = {
  vus: 5,
  duration: '30s',
  thresholds: {
    http_req_duration: ['p(99)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

export function handleSummary(data) {
  return {
    'results.json': JSON.stringify(data, null, 2),
  };
}

export default function () {
  const healthRes = http.get(`${BASE_URL}${API_PATHS.health}`);
  check(healthRes, {
    'health status is 200': (r) => r.status === 200,
  });

  sleep(1);

  const catalogRes = http.get(`${BASE_URL}${API_PATHS.products}`);
  check(catalogRes, {
    'mod-store catalog is 200': (r) => r.status === 200,
  });

  sleep(1);
}
