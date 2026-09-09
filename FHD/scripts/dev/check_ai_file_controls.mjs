/** Native browser acceptance for user file selection -> AI file ID -> real upload input. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'

const root = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const frontend = resolve(root, 'frontend')
const require = createRequire(resolve(frontend, 'package.json'))
const { build } = require('esbuild')
const { chromium } = require('playwright')
const bundle = await build({
  stdin: {
    contents: `export * from './src/composables/aiopenFileControls'; export { productReadAccountEpoch } from './src/utils/productReadAccountScope'`,
    resolveDir: frontend,
    loader: 'ts',
  },
  bundle: true, write: false, format: 'iife', globalName: 'FileControls',
  alias: { '@': resolve(frontend, 'src') },
  define: { 'process.env.NODE_ENV': '"test"' },
})
const browser = await chromium.launch({ headless: true })
const directory = await mkdtemp(resolve(tmpdir(), 'xcmax-ai-file-'))
try {
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('http://127.0.0.1/fixture', route => route.fulfill({ contentType: 'text/html', body: '<main><input id="source" type="file" multiple><input id="target" type="file" hidden accept=".csv"></main>' }))
  await page.goto('http://127.0.0.1/fixture')
  await page.addScriptTag({ content: bundle.outputFiles[0].text })
  await page.evaluate(() => {
    document.addEventListener('change', FileControls.captureScreenFileSelection, true)
    window.uploads = []
    document.querySelector('#target').addEventListener('change', async event => {
      const selected = event.target.files[0]
      window.uploads.push(selected ? await selected.text() : '')
    })
  })
  const csvPath = resolve(directory, 'customer.csv')
  const pdfPath = resolve(directory, 'document.pdf')
  await writeFile(csvPath, 'name,quantity\n客户甲,3\n')
  await writeFile(pdfPath, '%PDF-test')
  await page.locator('#source').setInputFiles([csvPath, pdfPath])
  const catalog = await page.evaluate(() => FileControls.listScreenFiles())
  assert.equal(catalog.files.length, 2, `Native file selection must be captured: ${JSON.stringify(errors)}`)
  const csv = catalog.files.find(file => file.name === 'customer.csv').file_id
  const pdf = catalog.files.find(file => file.name === 'document.pdf').file_id
  const selected = await page.evaluate(id => FileControls.setScreenFiles(document.querySelector('#target'), { file_ids: [id] }, () => {}), csv)
  assert.equal(selected.success, true)
  await page.waitForFunction(() => window.uploads.length === 1)
  assert.deepEqual(await page.evaluate(() => window.uploads), ['name,quantity\n客户甲,3\n'])
  const rejected = await page.evaluate(id => FileControls.setScreenFiles(document.querySelector('#target'), { file_ids: [id] }, () => {}), pdf)
  assert.equal(rejected.success, false)
  assert.equal(await page.locator('#target').evaluate(input => input.files[0].name), 'customer.csv')
  assert.equal((await page.evaluate(() => FileControls.listScreenFiles())).files.length, 2, 'Synthetic events must not create new file grants')
  const cleared = await page.evaluate(() => FileControls.setScreenFiles(document.querySelector('#target'), { file_ids: [] }, () => {}))
  assert.equal(cleared.success, true)
  await page.evaluate(() => FileControls.productReadAccountEpoch.value++)
  const expired = await page.evaluate(id => FileControls.setScreenFiles(document.querySelector('#target'), { file_ids: [id] }, () => {}), csv)
  assert.equal(expired.success, false)
  assert.equal((await page.evaluate(() => FileControls.listScreenFiles())).files.length, 0)
  console.log('PASS: native selection, exact file content, one upload event, accept rejection, clear, account retirement')
} finally {
  await browser.close()
  await rm(directory, { recursive: true })
}
