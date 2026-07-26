import { test, expect, type Route } from '@playwright/test';
import {
  E2E_PASSWORD,
  E2E_USER,
  installE2eShellMocks,
  captureEvidence,
  csrfHeaders,
  isFullStack,
  loginBrowserSession,
} from './helpers';

test.describe('P0 critical paths', () => {
  test.beforeEach(async ({ page }) => {
    if (!isFullStack()) {
      await installE2eShellMocks(page);
    } else {
      await loginBrowserSession(page);
    }
  });

  test('01 login — credentials establish session', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('#app')).toBeVisible();
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '01-login.png');
  });

  test('02 order — orders list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/orders', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    const orderNav = page.getByRole('button', { name: /订单|发货单|创建订单/ }).first();
    if (await orderNav.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await orderNav.click();
    }
    await captureEvidence(page, '02-order.png');
  });

  test('03 shipment — shipment list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/shipment/list', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '03-shipment.png');
  });

  test('04 OCR — ocr test endpoint reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/ocr/test', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '04-ocr.png');
  });

  test('05 mod — mods list API reachable', async ({ page, request }) => {
    if (isFullStack()) {
      const resp = await request.get('/api/mods/', { timeout: 20_000 });
      expect(resp.status(), await resp.text()).toBeLessThan(500);
    }

    await page.goto('/ai-ecosystem', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 });
    await captureEvidence(page, '05-mod.png');
  });

  test('06 order data loop — 创建、编辑、导出并回读出货单', async ({ page }) => {
    const apiBase = (
      process.env.MOD_PILOT_FHD_API ||
      process.env.PLAYWRIGHT_BASE_URL ||
      'http://127.0.0.1:5000'
    ).replace(/\/$/, '');
    const fetchJson = async (path: string, init: RequestInit = {}) => {
      if (isFullStack()) {
        const liveRequest = page.request;
        const method = String(init.method || 'GET').toUpperCase();
        const options = {
          data: init.body ? JSON.parse(String(init.body)) : undefined,
          headers: method === 'GET' ? {} : await csrfHeaders(liveRequest, {}, apiBase),
          timeout: 30_000,
        };
        const resp = await liveRequest.fetch(`${apiBase}${path}`, { ...options, method });
        const text = await resp.text();
        let body: any = {};
        try {
          body = JSON.parse(text || '{}');
        } catch {
          body = {};
        }
        return { status: resp.status(), text, body };
      }
      return page.evaluate(
        async ({ path, init }) => {
          const resp = await fetch(path, init);
          const text = await resp.text();
          let body: any = {};
          try {
            body = JSON.parse(text || '{}');
          } catch {
            body = {};
          }
          return { status: resp.status, text, body };
        },
        { path, init }
      );
    };

    const unitName = `E2E客户-${Date.now()}`;
    const updatedUnitName = `${unitName}-已编辑`;
    let orderId = '';

    if (!isFullStack()) {
      const mockOrder = {
        id: 1001,
        purchase_unit: unitName,
        product_name: 'E2E产品',
        quantity_kg: 10,
        status: 'pending',
      };
      const handleOrderCollection = (route: Route) => {
        if (route.request().method() === 'POST') {
          return route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify({ success: true, shipment: mockOrder }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: [mockOrder], count: 1 }),
        });
      };
      await page.route(
        /\/api\/(?:mod\/[^/]+\/)?orders(?:\?.*)?$/,
        handleOrderCollection,
      );
      await page.route('**/api/orders/1001', async (route) => {
        if (route.request().method() === 'PATCH') {
          Object.assign(mockOrder, JSON.parse(route.request().postData() || '{}'));
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: mockOrder }),
        });
      });
      await page.route('**/api/orders/export**', (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          body: 'mock-xlsx',
        })
      );
      // Browser-side fetches need an HTTP origin; about:blank cannot resolve /api/* URLs.
      await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    } else {
      // Prime the browser-side enterprise session cache through the real login
      // UI before loading the deep link. A cookie-only session can be valid at
      // the API layer while the route guard still redirects the first /orders
      // navigation to the default workspace.
      await page.goto('/login?redirect=%2Forders', {
        waitUntil: 'domcontentloaded',
        timeout: 30_000,
      });
      await page.locator('#lv-username').fill(E2E_USER);
      await page.locator('#lv-password').fill(E2E_PASSWORD);
      const loginResponsePromise = page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          /\/api\/auth\/login(?:\?|$)/.test(response.url()),
        { timeout: 30_000 }
      );
      await page.locator('.login-submit').click();
      const loginResponse = await loginResponsePromise;
      const loginText = await loginResponse.text();
      expect(loginResponse.status(), loginText).toBe(200);
      expect(JSON.parse(loginText || '{}')?.success, loginText).toBe(true);
      await expect(page).toHaveURL(/\/orders(?:[?#]|$)/, { timeout: 30_000 });
      await expect(page.locator('#view-orders')).toBeVisible({ timeout: 25_000 });
    }

    const createResp = await fetchJson('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        purchase_unit: unitName,
        products: [
          {
            product_name: 'E2E产品',
            model_number: 'E2E-M1',
            quantity_tins: 1,
            tin_spec: 10,
            unit_price: 19.9,
            amount: 19.9,
          },
        ],
      }),
    });
    expect([200, 201], createResp.text).toContain(createResp.status);
    expect(createResp.body?.success, createResp.text).toBe(true);
    orderId = String(createResp.body?.shipment?.id || createResp.body?.data?.id || '1001');
    expect(orderId).not.toBe('');

    const updateResp = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        purchase_unit: updatedUnitName,
        product_name: 'E2E产品-已编辑',
        quantity_kg: 20,
        status: 'completed',
      }),
    });
    expect(updateResp.status, updateResp.text).toBe(200);
    expect(updateResp.body?.success, updateResp.text).toBe(true);

    const readResp = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`);
    expect(readResp.status, readResp.text).toBe(200);
    expect(readResp.body?.data?.purchase_unit).toBe(updatedUnitName);
    expect(readResp.body?.data?.product_name).toBe('E2E产品-已编辑');
    expect(readResp.body?.data?.status).toBe('completed');

    if (isFullStack()) {
      const exportResp = await page.request.get(`${apiBase}/api/orders/export`, {
        timeout: 30_000,
      });
      expect(exportResp.status(), await exportResp.text()).toBe(200);
      expect(exportResp.headers()['content-type'] || '').toContain('spreadsheetml');
      expect((await exportResp.body()).byteLength).toBeGreaterThan(100);
    }

    if (!isFullStack()) {
      await page.goto('/orders', { waitUntil: 'domcontentloaded', timeout: 30_000 });
      await expect(page.locator('#view-orders')).toBeVisible({ timeout: 25_000 });
    } else {
      const orderSearch = page.locator('#view-orders .search-box input');
      const searchResponse = page.waitForResponse(
        (response) => /\/api\/(?:mod\/[^/]+\/)?orders\/search(?:\?|$)/.test(response.url()),
        { timeout: 20_000 }
      );
      await orderSearch.fill('__e2e_refresh__');
      await searchResponse;
      const listResponse = page.waitForResponse(
        (response) => /\/api\/(?:mod\/[^/]+\/)?orders(?:\?|$)/.test(response.url()),
        { timeout: 20_000 }
      );
      await orderSearch.fill('');
      await listResponse;
    }
    await expect(page.getByText(updatedUnitName, { exact: true })).toBeVisible({ timeout: 20_000 });

    await captureEvidence(page, '06-order-data-loop.png');
  });

  test('07 material data loop — 创建、编辑、导出并回读材料', async ({ page }) => {
    test.skip(!isFullStack(), 'covered by the mandatory release full-stack job');
    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`);
    });
    page.on('requestfailed', (request) => {
      if (request.resourceType() === 'script') {
        browserErrors.push(
          `script: ${request.url()} (${request.failure()?.errorText || 'request failed'})`
        );
      }
    });
    const apiBase = (
      process.env.MOD_PILOT_FHD_API ||
      process.env.PLAYWRIGHT_BASE_URL ||
      'http://127.0.0.1:5000'
    ).replace(/\/$/, '');
    const requestJson = async (path: string, method = 'GET', data?: Record<string, unknown>) => {
      const headers = method === 'GET' ? {} : await csrfHeaders(page.request, {}, apiBase);
      const response = await page.request.fetch(`${apiBase}${path}`, {
        method,
        headers,
        data,
        timeout: 30_000,
      });
      const text = await response.text();
      return {
        status: response.status(),
        text,
        body: JSON.parse(text || '{}') as Record<string, any>,
      };
    };

    // Establish this page's session through the real login UI. Reusing only a
    // cookie leaves the browser-side enterprise session cache cold, so a deep
    // link can block on redundant remote validation while the Agent-backed
    // order work is settling. Login marks that cache valid without weakening
    // any auth, route, or CRUD assertion.
    await page.goto('/login?redirect=%2Forders', {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    await page.locator('#lv-username').fill(E2E_USER);
    await page.locator('#lv-password').fill(E2E_PASSWORD);
    const loginResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' && /\/api\/auth\/login(?:\?|$)/.test(response.url()),
      { timeout: 30_000 }
    );
    await page.locator('.login-submit').click();
    const loginResponse = await loginResponsePromise;
    const loginText = await loginResponse.text();
    expect(loginResponse.status(), loginText).toBe(200);
    expect(JSON.parse(loginText || '{}')?.success, loginText).toBe(true);
    await expect(page).toHaveURL(/\/orders(?:[?#]|$)/, { timeout: 30_000 });
    await expect(page.locator('#view-orders')).toBeVisible({ timeout: 25_000 });
    await page.goto('/materials', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await expect(page).toHaveURL(/\/materials(?:[?#]|$)/, { timeout: 30_000 });
    try {
      await expect(page.locator('#view-materials')).toBeVisible({ timeout: 25_000 });
    } catch (error) {
      await captureEvidence(page, '07-material-data-loop-failure.png').catch(() => undefined);
      const bodyText = await page
        .locator('body')
        .innerText()
        .catch(() => '<body unavailable>');
      const original = error instanceof Error ? error.message : String(error);
      throw new Error(
        `${original}\nMaterial page diagnostics:\n${browserErrors.join('\n') || '<no browser errors>'}\nBody:\n${bodyText.slice(0, 4000)}`
      );
    }

    const stamp = Date.now();
    const materialName = `E2E材料-${stamp}`;
    const updatedName = `${materialName}-已编辑`;
    const created = await requestJson('/api/materials', 'POST', {
      material_code: `E2E-MAT-${stamp}`,
      name: materialName,
      category: 'E2E验收',
      unit: 'kg',
      quantity: 12,
      unit_price: 8.5,
      supplier: 'E2E供应商',
    });
    expect(created.status, created.text).toBe(200);
    expect(created.body.success, created.text).toBe(true);
    const materialId = String(created.body?.data?.id || '');
    expect(materialId).not.toBe('');

    const updated = await requestJson(`/api/materials/${encodeURIComponent(materialId)}`, 'PUT', {
      name: updatedName,
      category: 'E2E验收-已编辑',
      quantity: 24,
      unit_price: 9.75,
    });
    expect(updated.status, updated.text).toBe(200);
    expect(updated.body.success, updated.text).toBe(true);

    const listed = await requestJson(`/api/materials?search=${encodeURIComponent(updatedName)}`);
    expect(listed.status, listed.text).toBe(200);
    const rows = Array.isArray(listed.body?.data) ? listed.body.data : [];
    expect(rows.some((row: any) => String(row.id) === materialId && row.name === updatedName)).toBe(true);

    const exported = await page.request.get(`${apiBase}/api/materials/export`, { timeout: 30_000 });
    expect(exported.status(), await exported.text()).toBe(200);
    expect(exported.headers()['content-type'] || '').toContain('spreadsheetml');
    expect((await exported.body()).byteLength).toBeGreaterThan(100);

    await page.locator('#view-materials .search-box input').fill(updatedName);
    await expect(page.getByText(updatedName, { exact: true })).toBeVisible({ timeout: 20_000 });
    await captureEvidence(page, '07-material-data-loop.png');
  });
});
