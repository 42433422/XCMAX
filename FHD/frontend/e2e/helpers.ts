import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import type { APIRequestContext, Page } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const E2E_USER = process.env.E2E_USER || 'admin';
export const E2E_PASSWORD = process.env.E2E_PASSWORD || 'admin123';

export function isFullStack(): boolean {
  return process.env.E2E_FULL_STACK === '1';
}

/** P0 证据截图目录（相对 frontend/） */
export function evidenceDir(): string {
  return process.env.E2E_EVIDENCE_DIR || path.join(__dirname, '../../docs/evidence/e2e');
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
  extra: Record<string, string> = {}
): Promise<Record<string, string>> {
  await request.get('/api/health', { timeout: 15_000 });
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

export async function imUserHeaders(
  request: APIRequestContext,
  userId: string
): Promise<Record<string, string>> {
  return csrfHeaders(request, { 'X-User-ID': userId });
}
