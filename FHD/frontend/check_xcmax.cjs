const { chromium } = require('playwright');

(async () => {
  const targets = [
    { name: 'home', url: 'http://localhost:5001/' },
    { name: 'modstore', url: 'http://localhost:5001/mod-store' },
  ];

  const browser = await chromium.launch({ headless: true, channel: 'msedge' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`);
  });
  page.on('pageerror', err => errors.push(`[pageerror] ${err.message}`));
  page.on('requestfailed', req => {
    const url = req.url();
    if (url.includes('localhost:5001') || url.includes('127.0.0.1')) {
      errors.push(`[requestfailed] ${req.method()} ${url} - ${req.failure()?.errorText}`);
    }
  });

  for (const t of targets) {
    try {
      console.log(`\n=== ${t.name}: ${t.url} ===`);
      const resp = await page.goto(t.url, { waitUntil: 'networkidle', timeout: 30000 });
      console.log(`status: ${resp?.status()}`);
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `/tmp/xcmax_${t.name}.png`, fullPage: false });
      const title = await page.title();
      console.log(`title: ${title}`);
      const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 600));
      console.log(`body preview:\n${bodyText}`);
    } catch (e) {
      console.log(`ERROR: ${e.message}`);
      try { await page.screenshot({ path: `/tmp/xcmax_${t.name}_error.png` }); } catch {}
    }
  }

  if (errors.length) {
    console.log('\n=== 收集到的错误 ===');
    [...new Set(errors)].slice(0, 20).forEach(e => console.log(e));
  } else {
    console.log('\n=== 无控制台错误 ===');
  }

  await browser.close();
})();
