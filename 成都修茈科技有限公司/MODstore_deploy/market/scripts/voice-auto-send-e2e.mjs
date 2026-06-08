/**
 * 端到端：假麦克风播放 TTS 音频 → FunASR 识别 → 停顿自动发送
 * 运行：node scripts/voice-auto-send-e2e.mjs
 */
import { chromium } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const wavPath = path.resolve(__dirname, '../test-edge.wav')
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'https://xiu-ci.com/market'
const token = process.env.MODSTORE_TOKEN || ''

if (!fs.existsSync(wavPath)) {
  console.error('缺少 test-edge.wav，请先运行 server-asr-test.sh 生成')
  process.exit(1)
}
if (!token) {
  console.error('请设置 MODSTORE_TOKEN 环境变量')
  process.exit(1)
}

const wavForChrome = wavPath.replace(/\\/g, '/')

async function main() {
  console.log('WAV:', wavForChrome)
  console.log('URL:', baseURL)

  const browser = await chromium.launch({
    headless: true,
    args: [
      `--use-file-for-fake-audio-capture=${wavForChrome}`,
      '--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream',
      '--autoplay-policy=no-user-gesture-required',
    ],
  })

  const context = await browser.newContext({
    permissions: ['microphone'],
    ignoreHTTPSErrors: true,
  })
  await context.addInitScript((t) => {
    localStorage.setItem('modstore_token', t)
  }, token)

  const page = await context.newPage()
  const wsTexts = []
  const consoleLogs = []
  page.on('console', (msg) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`))
  page.on('pageerror', (err) => consoleLogs.push(`[pageerror] ${err.message}`))
  page.on('websocket', (ws) => {
    console.log('WS open:', ws.url())
    if (!ws.url().includes('/api/asr/funasr')) return
    ws.on('framereceived', (f) => {
      try {
        const payload = typeof f.payload === 'string' ? f.payload : f.payload.toString()
        if (payload.startsWith('{')) {
          const msg = JSON.parse(payload)
          console.log('ASR recv:', JSON.stringify(msg).slice(0, 200))
          if (msg.text) wsTexts.push(String(msg.text).trim())
        }
      } catch { /* ignore */ }
    })
    ws.on('close', () => console.log('WS closed'))
  })

  await page.goto(`${baseURL}/workbench/home`, { waitUntil: 'networkidle', timeout: 60000 })

  await page.locator('.wb-sidebar-modes .wb-sidebar-mode-btn').nth(2).click({ timeout: 20000 })

  await page.waitForTimeout(3000)

  // 若未自动开麦，点 ▶（暂停态）或再切一次模式
  const listenHint = await page.locator('.wb-voice-dock__listen-hint').textContent().catch(() => '')
  console.log('Dock listen hint:', listenHint)
  if (!listenHint || !listenHint.includes('聆听')) {
    await page.locator('.wb-voice-dock__mic').click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(2000)
  }
  if (!(await page.locator('.wb-voice-dock__listen-hint').textContent().catch(() => '') || '').includes('聆听')) {
    await page.locator('button, [role="button"]').filter({ hasText: /^说$/ }).first().click().catch(() => {})
    await page.waitForTimeout(3000)
  }

  // 等待 transcript 或用户消息出现（自动发送后）
  const deadline = Date.now() + 45000
  let transcript = ''
  let userBubble = ''
  let assistantStarted = false
  while (Date.now() < deadline) {
    transcript = await page.locator('.wb-voice-dock textarea, .wb-voice-input, [class*="voice"] input').first().inputValue().catch(() => '')
    userBubble = await page.locator('.wb-voice-turn--user .wb-voice-turn__user, .wb-direct-user').last().textContent().catch(() => '') || ''
    assistantStarted = await page.locator('.wb-voice-turn--assistant .msg-body, .wb-voice-turn--live .msg-body').count().then((n) => n > 0).catch(() => false)
    const bodyText = await page.locator('body').innerText()
    if (/你好.*网页/.test(bodyText) || /你好.*网页/.test(transcript) || /你好.*网页/.test(userBubble)) break
    if (wsTexts.some((t) => /你好/.test(t))) {
      await page.waitForTimeout(2000)
      userBubble = await page.locator('.wb-voice-turn--user .wb-voice-turn__user').last().textContent().catch(() => '') || ''
      if (/你好/.test(userBubble)) break
    }
    await page.waitForTimeout(500)
  }

  const bodySnippet = (await page.locator('body').innerText()).slice(0, 800)
  const screenshot = path.resolve(__dirname, '../../voice-e2e-result.png')
  await page.screenshot({ path: screenshot, fullPage: false })

  console.log('\n--- Console ---')
  consoleLogs.slice(-30).forEach((l) => console.log(l))
  wsTexts.forEach((t, i) => console.log(`  [${i}] ${t}`))
  console.log('\n--- 页面 transcript ---')
  console.log(transcript || '(空)')
  console.log('\n--- 用户消息气泡 ---')
  console.log(userBubble || '(未出现)')
  console.log('\n--- AI 已开始回复 ---')
  console.log(assistantStarted ? '是' : '否')
  console.log('\n--- 页面摘要 ---')
  console.log(bodySnippet)

  await browser.close()

  const ok =
    wsTexts.some((t) => /网页|你好/.test(t)) &&
    (/网页|你好/.test(userBubble) || /网页|你好/.test(bodySnippet))

  const asrOnly = wsTexts.some((t) => /网页|你好/.test(t))
  if (asrOnly && !ok) {
    console.log('\n△ ASR 已识别，但页面未自动发送（停顿检测或前端版本问题）')
    process.exit(3)
  }

  if (ok) {
    console.log('\n✓ 端到端通过：识别到语音并出现在对话流中')
    process.exit(0)
  }
  console.log('\n✗ 未检测到自动发送（可能未部署最新前端或选择器需调整）')
  process.exit(2)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
