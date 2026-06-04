#!/usr/bin/env node
/**
 * 将 plan2026 五条链路各截一张图到 FHD/docs/evidence/e2e/
 * 用法：先确保 global-setup 已生成 e2e/.auth/user.json，且 :5001 可访问。
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const authFile = path.join(__dirname, '.auth', 'user.json');
const outDir = path.resolve(__dirname, '../../docs/evidence/e2e');
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5001';

const shots = [
  { file: '01-login-shell.png', path: '/login', wait: '.app-shell.is-ready' },
  { file: '02-product-list.png', path: '/products', wait: '.app-shell.is-ready' },
  { file: '03-assistant-float.png', path: '/', wait: '.assistant-float-toggle', click: '.assistant-float-toggle', waitAfter: '#xcagi-assistant-float-panel' },
  { file: '04-order-list.png', path: '/orders', wait: '.app-shell.is-ready' },
  { file: '05-order-print.png', path: '/orders', wait: '.app-shell.is-ready' },
];

if (!fs.existsSync(authFile)) {
  console.error(`缺少 ${authFile}，请先运行: npm run test:e2e:p0`);
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ baseURL, storageState: authFile });
const page = await context.newPage();

for (const shot of shots) {
  await page.goto(shot.path, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForSelector(shot.wait, { timeout: 30_000 });
  if (shot.click) {
    await page.locator(shot.click).click();
    if (shot.waitAfter) await page.waitForSelector(shot.waitAfter, { timeout: 15_000 });
  }
  const dest = path.join(outDir, shot.file);
  await page.screenshot({ path: dest, fullPage: false });
  console.log('wrote', dest);
}

await browser.close();
