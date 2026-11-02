// Render the deployed SPA in a fresh anonymous context; never accept its HTML shell as policy evidence.
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const origin = new URL(process.argv[2]).origin
const channel = process.argv[3]
if (channel && !['chrome', 'msedge'].includes(channel)) throw new Error('unsupported browser channel')
const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) })
try {
  const context = await browser.newContext({ serviceWorkers: 'block' })
  await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  const pages = {}
  for (const kind of ['service-agreement', 'privacy-policy', 'model-recipients']) {
    const path = `/login/legal/${kind}`
    const response = await page.goto(`${origin}${path}`, { waitUntil: 'domcontentloaded' })
    if (!response?.ok() || page.url() !== `${origin}${path}`) throw new Error('policy response or redirect')
    const article = page.locator('main.login-legal > article')
    await article.waitFor({ state: 'visible' })
    pages[kind] = {
      title: await article.locator(':scope > h1').innerText(),
      version: await article.locator(':scope > p').first().innerText(),
      sections: await article.locator(':scope > section').allInnerTexts(),
      policy_links: await article.locator(':scope > nav a:visible').evaluateAll(links => links.map(link => link.href)),
    }
  }
  const response = await page.goto(`${origin}/login`, { waitUntil: 'domcontentloaded' })
  if (!response?.ok() || page.url() !== `${origin}/login`) throw new Error('login response or redirect')
  await page.locator('a[href="/login/legal/privacy-policy"]').first().waitFor({ state: 'visible' })
  pages.login_links = await page.locator('a:visible').evaluateAll(links => links.map(link => link.href))
  process.stdout.write(JSON.stringify(pages))
} finally {
  await browser.close()
}
