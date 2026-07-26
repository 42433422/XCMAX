import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import type { APIRequestContext, Page } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const E2E_USER = process.env.E2E_USER || 'xcagi-enterprise-demo';
export const E2E_PASSWORD = process.env.E2E_PASSWORD || 'Demo@2026';
export const E2E_ACCOUNT_KIND = process.env.E2E_ACCOUNT_KIND || 'enterprise';

export function isFullStack(): boolean {
  return process.env.E2E_FULL_STACK === '1';
}

/**
 * P0 证据截图目录。
 *
 * 只有真实全栈验收才默认刷新仓库内的验收证据；本地/CI mock smoke 写入
 * 已忽略的 Playwright 报告目录，避免一键发布门禁污染候选工作树。
 */
export function evidenceDir(): string {
  if (process.env.E2E_EVIDENCE_DIR) return process.env.E2E_EVIDENCE_DIR;
  if (isFullStack()) return path.join(__dirname, '../../docs/evidence/e2e');
  return path.join(__dirname, '../playwright-report/evidence');
}

export async function captureEvidence(page: Page, filename: string): Promise<void> {
  const dir = evidenceDir();
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, filename), fullPage: false });
}

const E2E_SESSION_PAYLOAD = {
  success: true,
  valid: true,
  data: {
    valid: true,
    username: 'e2e-user',
    role: 'user',
    account_kind: 'personal',
  },
};

/** 绕过 App.vue 启动鉴权 + 企业版路由守卫，使主壳可测。 */
export async function installE2eShellMocks(page: Page): Promise<void> {
  await page.route('**/api/runtime/product-sku**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { sku: 'personal' } }),
    });
  });
  await page.route('**/api/auth/session/validate**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(E2E_SESSION_PAYLOAD),
    });
  });
  await page.route('**/api/auth/me**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          user: { id: 1, username: 'e2e-user', role: 'user' },
          permissions: [],
        },
      }),
    });
  });
}

/** @deprecated 使用 installE2eShellMocks */
export const installPersonalSkuMocks = installE2eShellMocks;

/** 与 pytest ``_csrf_headers`` 一致：先打 health 拿 csrf_token cookie。 */
export async function csrfHeaders(
  request: APIRequestContext,
  extra: Record<string, string> = {},
  apiBase = ''
): Promise<Record<string, string>> {
  const base = apiBase.replace(/\/$/, '');
  await request.get(`${base}/api/health`, { timeout: 15_000 });
  const state = await request.storageState();
  const csrf =
    state.cookies.find((c) => c.name === 'csrf_token')?.value ||
    state.cookies.find((c) => c.name === 'csrf-token')?.value ||
    '';
  return {
    'Content-Type': 'application/json',
    ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    ...extra,
  };
}

export async function loginBrowserSession(page: Page, apiBase = ''): Promise<void> {
  const base = (apiBase || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001').replace(
    /\/$/,
    ''
  );

  let lastTransientError: unknown;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const headers = await csrfHeaders(page.request, {}, base);
      const resp = await page.request.post(`${base}/api/auth/login`, {
        headers,
        data: {
          username: E2E_USER,
          password: E2E_PASSWORD,
          account_kind: E2E_ACCOUNT_KIND,
        },
        timeout: 20_000,
      });
      const body = await resp.json().catch(() => ({}));
      if (resp.status() >= 500) {
        throw new Error(
          `E2E login transient failure: status=${resp.status()} body=${JSON.stringify(body)}`
        );
      }
      if (body?.success !== true) {
        throw new Error(`E2E login failed: status=${resp.status()} body=${JSON.stringify(body)}`);
      }

      const meResp = await page.request.get(`${base}/api/auth/me`, { timeout: 20_000 });
      const meBody = await meResp.json().catch(() => ({}));
      if (meResp.status() >= 500) {
        throw new Error(
          `E2E auth verification transient failure: status=${meResp.status()} body=${JSON.stringify(meBody)}`
        );
      }
      if (meBody?.success !== true || !meBody?.data?.user) {
        throw new Error(
          `E2E auth verification failed: status=${meResp.status()} body=${JSON.stringify(meBody)}`
        );
      }
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const isTransient =
        message.includes('transient failure') ||
        message.includes('Timeout') ||
        message.includes('timed out') ||
        message.includes('ECONNRESET') ||
        message.includes('ECONNREFUSED');
      if (!isTransient || attempt === 2) throw error;
      lastTransientError = error;
    }
  }

  throw lastTransientError;
}

export async function imUserHeaders(
  request: APIRequestContext,
  userId: string
): Promise<Record<string, string>> {
  return csrfHeaders(request, { 'X-User-ID': userId });
}
