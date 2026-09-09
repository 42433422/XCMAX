/** Real Vue components and Chromium: authenticated file download from a task result. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFile, mkdir, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const frontend = resolve(root, 'frontend')
const require = createRequire(resolve(frontend, 'package.json'))
const { build } = require('esbuild')
const { parse, compileScript, compileStyle } = require('@vue/compiler-sfc')
const { chromium } = require('playwright')
const content = Buffer.from('客户,数量\n甲客户,3\n乙客户,7\n')
const digest = createHash('sha256').update(content).digest('hex')
const id = 'a'.repeat(32)
const artifact = { artifact_id: id, name: '客户汇总.csv', uri: `/api/aiopen/artifacts/${id}`,
  metadata: { authenticated_download: true, size: content.length, sha256: digest, expires_at: Date.now() / 1000 + 3600 } }
const bundle = await build({
  stdin: { resolveDir: frontend, loader: 'ts', contents: `
    import { createApp } from 'vue';
    import Panel from './src/components/chat/AgentTaskRuntimePanel.vue';
    import { productReadAccountEpoch } from './src/utils/productReadAccountScope';
    window.retireAccount = () => productReadAccountEpoch.value++;
    const task = { id:'export-acceptance', type:'agent_task', title:'导出客户汇总', status:'success',
      payload: {runCount:1, attempt:1, eventCount:4, completedToolCount:1, artifactCount:1,
        steps:[{step_id:'export-step',tool_id:'aiopen',action:'api_call',description:'导出客户汇总',status:'completed'}],
        toolCalls:[{call_id:'export-call',tool_id:'aiopen',action:'api_call',status:'completed'}],
        finalOutput:{business_result:{summary:'客户汇总已生成，可下载文件。'}}, artifacts:[${JSON.stringify(artifact)}]} };
    const app=createApp(Panel,{task});
    app.config.globalProperties.$t=(key,params={})=>({'chat.runCount':'执行 '+params.count+' 次','chat.toolCount':'工具 '+params.count+' 个','chat.attemptCount':'尝试 '+params.count+' 次','chat.evidenceCount':'文件 '+params.count+' 个','chat.openTask':'打开任务'}[key]||key);
    app.mount('#app');
  ` },
  bundle: true, write: false, format: 'iife', alias: { '@': resolve(frontend, 'src') },
  define: { 'process.env.NODE_ENV': '"production"', 'import.meta.env': '{}', '__VUE_OPTIONS_API__': 'true', '__VUE_PROD_DEVTOOLS__': 'false', '__VUE_PROD_HYDRATION_MISMATCH_DETAILS__': 'false' },
  plugins: [{ name: 'real-vue-sfc', setup(builder) {
    builder.onLoad({ filter: /\.vue$/ }, async args => {
      const { descriptor, errors } = parse(await readFile(args.path, 'utf8'), { filename: args.path })
      assert.equal(errors.length, 0)
      const scope = 'data-v-' + createHash('sha256').update(args.path).digest('hex').slice(0, 8)
      const script = compileScript(descriptor, { id: scope, inlineTemplate: true })
      const styles = descriptor.styles.map(style => {
        const compiled = compileStyle({ source: style.content, filename: args.path, id: scope, scoped: style.scoped })
        assert.equal(compiled.errors.length, 0)
        return compiled.code
      }).join('\n')
      return { loader: 'ts', resolveDir: dirname(args.path), contents: script.content.replace('export default', 'const __fixtureComponent =') +
        `\n__fixtureComponent.__scopeId=${JSON.stringify(scope)};const style=document.createElement('style');style.textContent=${JSON.stringify(styles)};document.head.appendChild(style);export default __fixtureComponent;` }
    })
  } }],
})
const browser = await chromium.launch({ headless: true })
const temporary = await mkdtemp(resolve(tmpdir(), 'xcmax-artifact-ui-'))
try {
  const context = await browser.newContext({ viewport: { width: 900, height: 620 }, acceptDownloads: true })
  await context.addCookies([{ name: 'session_id', value: 'fixture-login', url: 'http://127.0.0.1' }])
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const baseCss = await readFile(resolve(frontend, 'src/styles/css/base.css'), 'utf8')
  await page.route('http://127.0.0.1/fixture', route => route.fulfill({ contentType: 'text/html', body:
    `<meta charset="utf-8"><style>${baseCss}body{background:#edf2f7;padding:44px;font-family:system-ui,'PingFang SC',sans-serif}main{background:white;padding:28px;border-radius:12px;max-width:700px;margin:auto}h1{font-size:20px;margin-bottom:12px}p.note{font-size:12px;color:#64748b;margin-bottom:20px}</style><main><h1>任务结果 · 客户汇总</h1><p class="note">组件验收页面 · 使用样例文件，不代表已安装版本</p><div id="app"></div></main>` }))
  let requests = 0
  let held
  await page.route(`**/api/aiopen/artifacts/${id}`, async route => {
    requests++
    assert.match(route.request().headers().cookie || '', /session_id=fixture-login/)
    if (requests === 2) { held = route; return }
    await route.fulfill({ contentType: 'text/csv', headers: { 'X-Content-SHA256': digest }, body: content })
  })
  await page.goto('http://127.0.0.1/fixture')
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  const section = page.getByRole('region', { name: '生成文件' })
  await section.waitFor({ state: 'visible' })
  const [download] = await Promise.all([page.waitForEvent('download'), section.getByRole('button', { name: '下载', exact: true }).click()])
  assert.equal(download.suggestedFilename(), '客户汇总.csv')
  const target = resolve(temporary, 'download.csv')
  await download.saveAs(target)
  assert.deepEqual(await readFile(target), content)
  await page.getByRole('status').filter({ hasText: '下载已发起' }).waitFor()
  const screenshot = resolve(root, 'docs/evidence/ai-full-control/task-artifact-download.png')
  await mkdir(dirname(screenshot), { recursive: true })
  await page.screenshot({ path: screenshot })
  let extraDownloads = 0
  page.on('download', () => extraDownloads++)
  await section.getByRole('button', { name: '下载', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('[aria-label="生成文件"] button')?.disabled)
  await page.evaluate(() => window.retireAccount())
  await page.waitForFunction(() => !document.querySelector('[aria-label="生成文件"] button')?.disabled)
  if (held) await held.abort().catch(() => {})
  assert.equal(extraDownloads, 0)
  assert.deepEqual(errors, [])
  process.stdout.write(`PASS: rendered task action, authenticated request, exact downloaded bytes, account retirement\nScreenshot: ${screenshot}\n`)
} finally {
  await browser.close()
  await rm(temporary, { recursive: true, force: true })
}
