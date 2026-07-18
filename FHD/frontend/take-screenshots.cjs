const { chromium } = require('playwright');
const path = require('path');

const SCREENSHOTS_DIR = path.resolve(__dirname, '../../成都修茈科技有限公司/assets/screenshots');
const BASE = 'http://localhost:17500';

const PAGES = [
  { path: '/', name: 'hero-chat.png', wait: 3000 },
  { path: '/workflow-employee-space', name: 'hero-workforce.png', wait: 3000 },
  { path: '/workflow-employee-space/stitch-full', name: 'workforce-panorama.png', wait: 3000 },
  { path: '/im', name: 'im-messenger.png', wait: 3000 },
  { path: '/persy/knowledge', name: 'knowledge-persy.png', wait: 3000 },
  { path: '/ai-ecosystem', name: 'ai-ecosystem.png', wait: 3000 },
  { path: '/mod-store', name: 'mod-store.png', wait: 3000 },
  { path: '/ai-groups', name: 'ai-group-chat.png', wait: 4000 },
  { path: '/products', name: 'transform-attendance.png', wait: 3000 },
];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // Login
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  await page.fill('input[placeholder="市场账号或邮箱"]', 'xcagi-enterprise-demo');
  await page.fill('input[placeholder="密码"]', 'Demo@2026');
  await page.click('button:has-text("登 录")');
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15000 });
  console.log('Logged in, landed on:', page.url());

  for (const p of PAGES) {
    try {
      await page.goto(`${BASE}${p.path}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(p.wait);
      const filePath = path.join(SCREENSHOTS_DIR, p.name);
      await page.screenshot({ path: filePath, fullPage: false });
      console.log(`Saved: ${p.name}`);
    } catch (err) {
      console.error(`Failed: ${p.name} - ${err.message.split('\n')[0]}`);
    }
  }

  await browser.close();
  console.log('Done');
})();
