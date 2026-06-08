/**
 * Mod 商家试点四图 · 真实 UI 流程（禁止脚本伪造入账）
 * 前置: bash FHD/scripts/dev/capture_mod_pilot_evidence.sh
 *
 * 环境变量:
 *   MOD_PILOT_ADMIN_USER/PASSWORD  — 管理后台 catalog（默认 testuser）
 *   MOD_PILOT_MERCHANT_USER/PASSWORD — 企业商家（默认 modpilot）
 *   MOD_PILOT_ALIPAY_BUYER / MOD_PILOT_ALIPAY_BUYER_PASS — 支付宝沙箱买家（可选，用于自动付 0.01）
 */
import { test, expect } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE = path.resolve(__dirname, '../../docs/evidence/mod');
const MARKET = process.env.MOD_PILOT_MARKET_URL || 'http://127.0.0.1:5176';
/** API 根（本地 Vite 代理用 MARKET；官网用 https://xiu-ci.com） */
const MARKET_API = process.env.MOD_PILOT_MARKET_API || MARKET;
const FHD_WEB = process.env.MOD_PILOT_FHD_URL || 'http://127.0.0.1:5001';
const FHD_API = process.env.MOD_PILOT_FHD_API || '';
const ADMIN_USER = process.env.MOD_PILOT_ADMIN_USER || process.env.MOD_PILOT_USER || 'testuser';
const ADMIN_PASS = process.env.MOD_PILOT_ADMIN_PASSWORD || process.env.MOD_PILOT_PASSWORD || 'ModPilot2026!';
const MERCHANT_USER = process.env.MOD_PILOT_MERCHANT_USER || 'modpilot';
const MERCHANT_PASS = process.env.MOD_PILOT_MERCHANT_PASSWORD || 'ModPilot2026!';
const SANDBOX_BUYER = process.env.MOD_PILOT_ALIPAY_BUYER || '';
const SANDBOX_BUYER_PASS = process.env.MOD_PILOT_ALIPAY_BUYER_PASS || '';

test.describe.configure({ mode: 'serial' });
test.setTimeout(300_000);

test.beforeAll(async () => {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  // Mod 试点依赖独立 MODstore；未启动时跳过整组（见 scripts/dev/run_mod_pilot_local.sh）
  try {
    const res = await fetch(`${MARKET_API}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) test.skip(true, `MODstore 未就绪: ${MARKET_API}`);
  } catch {
    test.skip(true, `MODstore 未启动 (${MARKET})，跳过 mod-pilot 证据流`);
  }
});

async function shot(page: import('@playwright/test').Page, file: string) {
  await page.screenshot({ path: path.join(EVIDENCE, file), fullPage: true });
}

async function marketToken(username: string, password: string): Promise<string> {
  const res = await fetch(`${MARKET_API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  expect(res.ok).toBeTruthy();
  const body = await res.json();
  const token = body.access_token || body.token;
  expect(token).toBeTruthy();
  return String(token);
}

async function marketLogin(page: import('@playwright/test').Page, redirectPath: string, user: string, pass: string) {
  const token = await marketToken(user, pass);
  await page.goto(MARKET, { waitUntil: 'domcontentloaded' });
  await page.evaluate(
    ([accessToken, refreshToken]) => {
      localStorage.setItem('modstore_token', accessToken);
      if (refreshToken) localStorage.setItem('modstore_refresh_token', refreshToken);
    },
    [token, ''],
  );
  await page.goto(`${MARKET}${redirectPath}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  return token;
}

async function openModStore(page: import('@playwright/test').Page) {
  await page.goto(`${FHD_WEB}/mod-store`, { waitUntil: 'networkidle', timeout: 90_000 });
  if (await page.locator('.mod-store, .modstore-primary').first().isVisible({ timeout: 8_000 }).catch(() => false)) {
    return;
  }
  await page.goto(`${FHD_WEB}/ai-ecosystem`, { waitUntil: 'networkidle', timeout: 60_000 });
  const launcher = page.getByRole('button', { name: /MOD 扩展|扩展市场/i }).first();
  if (await launcher.isVisible({ timeout: 10_000 }).catch(() => false)) {
    await launcher.click();
    await page.waitForTimeout(2000);
  }
}

async function fhdEnterpriseLogin(page: import('@playwright/test').Page, redirectPath = '/mod-store') {
  const fhdApi = FHD_API || FHD_WEB.replace(/\/$/, '');
  const res = await fetch(`${fhdApi}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ username: MERCHANT_USER, password: MERCHANT_PASS, account_kind: 'enterprise' }),
  });
  expect(res.ok).toBeTruthy();
  const body = await res.json();
  expect(body.success).toBeTruthy();
  const sessionId = String(body.session_id || '');
  expect(sessionId).toBeTruthy();
  const marketToken = String(body.market_access_token || '');
  const webOrigin = new URL(FHD_WEB).origin;
  await page.context().addCookies([
    {
      name: 'session_id',
      value: sessionId,
      url: webOrigin,
      httpOnly: true,
      secure: webOrigin.startsWith('https'),
      sameSite: 'Lax',
    },
  ]);
  await page.goto(FHD_WEB, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.evaluate((tok) => {
    localStorage.setItem('xcagi_platform_shell_mode', '1');
    if (tok) {
      localStorage.setItem('market_access_token', tok);
      localStorage.setItem('modstore_token', tok);
    }
  }, marketToken);
  if (redirectPath.includes('mod-store')) {
    await openModStore(page);
  } else {
    await page.goto(`${FHD_WEB}${redirectPath}`, { waitUntil: 'networkidle', timeout: 90_000 });
  }
  const splash = page.locator('[aria-label*="初始化"], [title*="跳过"]').first();
  if (await splash.isVisible({ timeout: 8_000 }).catch(() => false)) {
    await splash.click();
  }
}

async function trySandboxPay(page: import('@playwright/test').Page) {
  if (!SANDBOX_BUYER || !SANDBOX_BUYER_PASS) return;
  const buyerInput = page.locator('input[name="logonId"], input#logonId, input[placeholder*="支付宝"]').first();
  if (await buyerInput.isVisible({ timeout: 8_000 }).catch(() => false)) {
    await buyerInput.fill(SANDBOX_BUYER);
    const pwd = page.locator('input[type="password"]').first();
    if (await pwd.isVisible().catch(() => false)) await pwd.fill(SANDBOX_BUYER_PASS);
    const loginBtn = page.getByRole('button', { name: /登录|下一步|Next/i }).first();
    if (await loginBtn.isVisible().catch(() => false)) await loginBtn.click();
  }
  const payBtn = page.getByRole('button', { name: /确认付款|立即支付|Pay Now|确认/i }).first();
  if (await payBtn.isVisible({ timeout: 15_000 }).catch(() => false)) {
    await payBtn.click();
  }
}

async function waitOrderPaid(token: string, orderId: string, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(
      `${MARKET_API}/api/payment/query/${encodeURIComponent(orderId)}?reconcile=true`,
      { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' } },
    );
    if (res.ok) {
      const data = await res.json();
      if (String(data.status).toLowerCase() === 'paid') return data;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`订单 ${orderId} 在 ${timeoutMs / 1000}s 内未变为 paid（需完成支付宝沙箱付款）`);
}

test('01-listing · admin catalog', async ({ page }) => {
  await marketLogin(page, '/admin/database', ADMIN_USER, ADMIN_PASS);
  await expect(page.getByRole('heading', { name: '数据库管理' })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.db-section').filter({ hasText: '商品目录' }).locator('tbody tr').first()).toBeVisible({
    timeout: 30_000,
  });
  await shot(page, '01-listing.png');
});

test('02-store-page · ai-store', async ({ page }) => {
  await marketLogin(page, '/ai-store', MERCHANT_USER, MERCHANT_PASS);
  await shot(page, '02-store-page.png');
});

function parseOrderIdFromAlipayUrl(url: string): string {
  try {
    const u = new URL(url);
    const biz = u.searchParams.get('biz_content');
    if (biz) {
      const parsed = JSON.parse(biz) as { out_trade_no?: string };
      if (parsed.out_trade_no) return parsed.out_trade_no;
    }
  } catch {
    /* fall through */
  }
  const m = url.match(/out_trade_no[=:%22]+(MOD[0-9A-Za-z]+)/);
  return m?.[1] || '';
}

test('03-payment · 真实 checkout + 沙箱 0.01', async ({ page }) => {
  test.skip(
    !SANDBOX_BUYER || !SANDBOX_BUYER_PASS,
    '需配置 MOD_PILOT_ALIPAY_BUYER / MOD_PILOT_ALIPAY_BUYER_PASS 才能完成沙箱付款'
  );
  const token = await marketLogin(page, '/recharge', MERCHANT_USER, MERCHANT_PASS);
  await page.locator('input.custom-input, input[type="number"]').first().fill('0.01');
  await page.getByRole('button', { name: '立即支付' }).click();
  await page.getByRole('button', { name: '继续' }).click();
  await page.waitForURL(/alipaydev|alipay\.com|gateway\.do/i, { timeout: 90_000 });
  const orderId = parseOrderIdFromAlipayUrl(page.url());
  expect(orderId).toMatch(/^MOD/);
  await trySandboxPay(page);
  await waitOrderPaid(token, orderId);
  await marketLogin(page, '/wallet', MERCHANT_USER, MERCHANT_PASS);
  await expect(page.getByText('当前余额')).toBeVisible({ timeout: 30_000 });
  const text = await page.locator('body').innerText();
  expect(text).toMatch(/0\.01|支付宝|alipay|wallet/i);
  await shot(page, '03-payment.png');
});

test('04-activated · FHD mod-store installed', async ({ page }) => {
  const loginRes = await fetch(`${FHD_API || FHD_WEB.replace(/\/$/, '')}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      username: MERCHANT_USER,
      password: MERCHANT_PASS,
      account_kind: 'enterprise',
    }),
  }).catch(() => null);
  if (!loginRes?.ok) {
    test.skip(true, 'FHD 企业商家登录不可用，跳过 mod-store 激活截图');
  }
  await fhdEnterpriseLogin(page, '/mod-store');
  const storeRoot = page.locator('.mod-store, .modstore-primary, [data-testid="mod-store"]').first();
  if (!(await storeRoot.isVisible({ timeout: 30_000 }).catch(() => false))) {
    test.skip(true, 'mod-store 页面未加载（需企业会话 + mod 路由）');
  }
  await expect(storeRoot).toBeVisible();
  await expect(page.getByText(/MOD 扩展/)).toBeVisible({ timeout: 15_000 });
  const installBtn = page.getByRole('button', { name: /安装|Install/i }).first();
  if (await installBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await installBtn.click();
    await page.waitForTimeout(3000);
  }
  const installed = page.locator('.installed-badge, .mod-card.installed').first();
  await expect(installed).toBeVisible({ timeout: 60_000 });
  await shot(page, '04-activated.png');
});
