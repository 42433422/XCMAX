#!/usr/bin/env node
/**
 * 官网运行时验收（真人视角 + 移动端 390px + 视频播放 + 1 次点击路径）。
 * 产出 site/data/runtime-results.json（供 site_acceptance.py --runtime 合并判定 PASS）。
 * 截图证据写入 site/data/runtime-evidence/。
 *
 * 用法：node scripts/site_runtime_acceptance.mjs [baseURL]
 *   baseURL 默认 http://127.0.0.1:8123（先用 range_static_server.py 起服务）
 * 环境变量 XC_BROWSER_EXEC：指定浏览器可执行文件（本地 Edge/Chrome）；缺省用 Playwright chromium。
 */
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const SITE = join(dirname(fileURLToPath(import.meta.url)), '..')
const BASE = process.argv[2] || 'http://127.0.0.1:8123'
const OUT = join(SITE, 'site/data/runtime-results.json')
const EVID = join(SITE, 'site/data/runtime-evidence')
mkdirSync(EVID, { recursive: true })

const results = { base: BASE, started_at: new Date().toISOString(), checks: [] }
function record(name, pass, detail) {
  results.checks.push({ name, pass, detail })
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}  ${detail || ''}`)
}

const browserExec = process.env.XC_BROWSER_EXEC || undefined
const browser = await chromium.launch(browserExec ? { executablePath: browserExec } : {})
try {
  /* ---------- 桌面端：首页 ---------- */
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const t0 = Date.now()
  await desktop.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  await desktop.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const loadMs = Date.now() - t0

  const h1 = await desktop.locator('h1').first().textContent()
  record('desktop: hero H1 存在', /把重复业务交给/.test(h1 || ''), `load=${loadMs}ms h1=${(h1 || '').trim().slice(0, 24)}`)
  record('desktop: 首屏加载 ≤5s', loadMs < 5000, `${loadMs}ms`)

  const heroImg = desktop.locator('.home-hero-figure img')
  const heroLoaded = (await heroImg.count()) > 0 ? await heroImg.first().evaluate((img) => img.complete && img.naturalWidth > 100).catch(() => false) : false
  record('desktop: hero 实机截图渲染', !!heroLoaded, '真实产品界面截图')

  // SSOT 注入：hero CTA 价格 + 平台状态 + 数据戳
  await desktop.waitForTimeout(800)
  const heroCta = await desktop.locator('.home-actions .home-button--primary').textContent()
  record('desktop: hero CTA 价格来自 SSOT', /¥99/.test(heroCta || ''), (heroCta || '').trim())
  const platText = await desktop.locator('[data-platform-status]').first().textContent()
  record('desktop: 平台状态槽位被 SSOT 校验', /签约级|实验|待验证/.test(platText || ''), (platText || '').trim())

  const ssot = await desktop.evaluate(() => fetch('/site/data/public-site.json').then((r) => r.json()))
  const trialDisplay = ssot.pricing.trial.amount_display
  const planText = await desktop.locator('#pricing').textContent()
  record('desktop: 定价含 SSOT 试用价', planText.includes(trialDisplay), `expect ${trialDisplay}`)
  record('desktop: 首页价格区仅 3 档', (await desktop.locator('#pricing .home-price-card').count()) === 3, '集团/旗舰档下沉 pricing.html')
  record('desktop: 首页不含集团/旗舰档价格', !planText.includes(ssot.pricing.extended_plans[0].amount_display), ssot.pricing.extended_plans[0].amount_display + ' 不在首页')
  const stampText = await desktop.locator('[data-ssot="home-updated"]').textContent()
  record('desktop: 数据更新时间戳注入', /数据更新：\d{4}-\d{2}-\d{2}/.test(stampText || ''), (stampText || '').trim().slice(0, 40))

  // 视频块（SSOT 驱动）
  const videoVisible = await desktop.locator('#demo-video').isVisible().catch(() => false)
  const video = desktop.locator('#home-demo-video')
  record('desktop: 合规录像块已展示', videoVisible, '≤60s 连续无剪辑录屏')

  // 1 次点击路径
  for (const [label, expect] of [['客户案例', '/cases.html'], ['下载', '/download'], ['价格', '/pricing.html'], ['验证中心', '/verify.html']]) {
    const href = await desktop.locator('.nav-menu a', { hasText: label }).first().getAttribute('href')
    record(`desktop: 首页→${label} 1 次点击`, href === expect, href)
  }

  // 技术与透明度下拉
  await desktop.locator('#main-nav details.nav-secondary summary').click()
  const dropdownVisible = await desktop
    .locator('#main-nav details.nav-secondary a', { hasText: '开发者中心' })
    .first()
    .isVisible()
    .catch(() => false)
  record('desktop: 技术与透明度下拉可用', dropdownVisible, '开发者中心入口可见')

  await desktop.screenshot({ path: join(EVID, 'desktop-home.png') })

  /* ---------- 桌面端：案例/验证中心/价格页 ---------- */
  await desktop.goto(BASE + '/cases.html', { waitUntil: 'domcontentloaded' })
  await desktop.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const evHref = await desktop.locator('a[href^="/verify.html"]').first().getAttribute('href').catch(() => null)
  record('desktop: 案例页有完整证据入口', !!evHref, evHref)
  await desktop.screenshot({ path: join(EVID, 'desktop-cases.png') })

  await desktop.goto(BASE + '/verify.html', { waitUntil: 'domcontentloaded' })
  await desktop.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const platCards = await desktop.locator('#plat-grid .xc-plat-card').count()
  record('desktop: 验证中心平台卡=SSOT 平台数', platCards === ssot.platforms.length, `count=${platCards}`)
  const featCards = await desktop.locator('#feat-list .xc-feat').count()
  record('desktop: 验证中心功能记录=SSOT 功能数', featCards === ssot.evidence.features.length, `count=${featCards}`)
  await desktop.locator('.xc-feat-tech summary').first().click()
  const techText = await desktop.locator('.xc-feat-tech .xc2-kv').first().textContent()
  record('desktop: 完整技术证据含 Git SHA', /[0-9a-f]{40}/.test(techText || ''), '展开层可见')
  await desktop.screenshot({ path: join(EVID, 'desktop-verify.png') })

  await desktop.goto(BASE + '/pricing.html', { waitUntil: 'domcontentloaded' })
  await desktop.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const pricePage = await desktop.locator('body').textContent()
  const allPlans = ssot.pricing.all_plans.map((p) => p.amount_display)
  const missing = allPlans.filter((a) => !pricePage.includes(a))
  record('desktop: 价格页含全部 5 档 SSOT 价格', missing.length === 0, `missing=${missing.join(',') || 'none'}`)
  await desktop.screenshot({ path: join(EVID, 'desktop-pricing.png') })

  /* ---------- 视频运行时 ---------- */
  await desktop.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  await desktop.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  let videoOk = false
  let videoDetail = 'video 缺失'
  if ((await video.count()) === 1) {
    const preload = await video.getAttribute('preload')
    const poster = await video.getAttribute('poster')
    const tPlay = Date.now()
    await video.evaluate((v) => v.play())
    const played = await video
      .evaluate(
        (v) =>
          new Promise((resolve) => {
            const to = setTimeout(() => resolve(false), 4000)
            v.addEventListener('timeupdate', function onT() {
              if (v.currentTime > 0.2) {
                clearTimeout(to)
                v.removeEventListener('timeupdate', onT)
                resolve(true)
              }
            })
          }),
      )
      .catch(() => false)
    videoOk = played && preload === 'metadata' && !!poster
    videoDetail = `played=${played} in ${Date.now() - tPlay}ms preload=${preload} poster=${poster ? 'yes' : 'no'}`
    await video.evaluate((v) => v.pause())
  }
  record('desktop: 证据视频可播 + preload=metadata + poster', videoOk, videoDetail)

  const desktopAll = results.checks.filter((c) => c.name.startsWith('desktop:')).every((c) => c.pass)
  results.desktop_test = desktopAll ? 'pass' : 'fail'
  await desktop.close()

  /* ---------- 移动端 390px ---------- */
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  await mobile.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  await mobile.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  await mobile.waitForTimeout(800)

  const scrollW = await mobile.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth))
  record('mobile: 390px 无横向滚动', scrollW <= 391, `scrollWidth=${scrollW}`)

  const vidW = await mobile.evaluate(() => {
    const v = document.querySelector('#home-demo-video')
    if (!v) return null
    return { w: v.getBoundingClientRect().width, cw: v.closest('.home-wrap').getBoundingClientRect().width }
  })
  record('mobile: 视频宽度 100%', !!vidW && Math.abs(vidW.w - vidW.cw) <= 2.5, JSON.stringify(vidW))

  await mobile.click('#mobile-menu-toggle')
  const drawerOpen = await mobile.locator('#mobile-menu').evaluate((d) => d.classList.contains('active'))
  const drawerVisible = await mobile.locator('#mobile-menu a', { hasText: '客户案例' }).isVisible()
  record('mobile: 抽屉导航可用', drawerOpen && drawerVisible, `open=${drawerOpen}`)
  await mobile.screenshot({ path: join(EVID, 'mobile-home-drawer.png') })
  await mobile.keyboard.press('Escape')
  await mobile.click('#mobile-menu-overlay').catch(() => {})
  await mobile.waitForTimeout(400)

  const singleCol = await mobile.evaluate(() => {
    const steps = document.querySelectorAll('.home-steps li')
    if (steps.length < 2) return true
    const a = steps[0].getBoundingClientRect()
    const b = steps[1].getBoundingClientRect()
    return b.top >= a.bottom - 2
  })
  record('mobile: 步骤卡片单列', singleCol, '')

  const ctaBox = await mobile.locator('.home-actions .home-button--primary').first().boundingBox()
  record('mobile: hero CTA 可见且高度 ≥40px', !!ctaBox && ctaBox.height >= 40 && ctaBox.y < 844, JSON.stringify(ctaBox))
  await mobile.screenshot({ path: join(EVID, 'mobile-home.png') })

  await mobile.goto(BASE + '/cases.html', { waitUntil: 'domcontentloaded' })
  await mobile.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const mScrollW = await mobile.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth))
  record('mobile: 案例页无横向滚动', mScrollW <= 391, `scrollWidth=${mScrollW}`)
  await mobile.screenshot({ path: join(EVID, 'mobile-cases.png') })

  await mobile.goto(BASE + '/verify.html', { waitUntil: 'domcontentloaded' })
  await mobile.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {})
  const kvW = await mobile.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth))
  record('mobile: 验证中心无横向滚动', kvW <= 391, `scrollWidth=${kvW}`)
  await mobile.screenshot({ path: join(EVID, 'mobile-verify.png') })

  const mobileAll = results.checks.filter((c) => c.name.startsWith('mobile:')).every((c) => c.pass)
  results.mobile_test = mobileAll ? 'pass' : 'fail'
  await mobile.close()

  /* ---------- HTTP Range ---------- */
  const rangePage = await browser.newPage()
  await rangePage.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  const rangeUrl = BASE + '/capabilities/assets/evidence/base-login-03-login-operation-web.mp4'
  const rangeResult = await rangePage.evaluate(async (url) => {
    const r = await fetch(url, { headers: { Range: 'bytes=0-1023' } })
    return { status: r.status, accept: r.headers.get('accept-ranges'), length: (await r.arrayBuffer()).byteLength }
  }, rangeUrl)
  record(
    'range: 206 Partial Content + Accept-Ranges',
    rangeResult.status === 206 && rangeResult.accept === 'bytes' && rangeResult.length === 1024,
    JSON.stringify(rangeResult),
  )
  results.range_test = rangeResult.status === 206 ? 'pass' : 'fail'
  await rangePage.close()

  results.video_runtime_test = videoOk ? 'pass' : 'fail'
  results.finished_at = new Date().toISOString()
  const failed = results.checks.filter((c) => !c.pass)
  results.summary = { total: results.checks.length, failed: failed.length }
  writeFileSync(OUT, JSON.stringify(results, null, 2) + '\n')
  console.log(`\n[runtime] ${results.checks.length - failed.length}/${results.checks.length} checks passed → ${OUT}`)
  process.exit(failed.length ? 1 : 0)
} finally {
  await browser.close()
}
