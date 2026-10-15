// Drives the packaged app's public preload API. No mocks or security overrides.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import http from 'node:http'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const [action, directory, candidate] = process.argv.slice(2)
const dir = path.resolve(directory)
if (action === 'prepare') {
  const receipt = JSON.parse(fs.readFileSync(path.join(dir, 'delivery-receipt.json'), 'utf8').replace(/^\uFEFF/, ''))
  if (receipt.git_sha !== process.env.CANDIDATE_SHA || !/^\d+\.\d+\.\d+\.\d+$/.test(receipt.version)) throw Error('Unexpected candidate identity')
  const bytes = fs.readFileSync(candidate)
  if (crypto.createHash('sha256').update(bytes).digest('hex') !== receipt.sha256) throw Error('Candidate receipt mismatch')
  const sha512 = crypto.createHash('sha512').update(bytes).digest('base64')
  const filename = path.basename(candidate)
  if (!/^[A-Za-z0-9._-]+$/.test(filename) || !/^[0-9a-f]{40}$/.test(receipt.git_sha)) throw Error('Invalid candidate identity')
  const body = [`version: ${receipt.version.split('.').slice(0, 3).join('.')}`, `productVersion: ${receipt.version}`, `buildSha: ${receipt.git_sha}`, `releaseDate: '${new Date().toISOString()}'`, 'files:', `  - url: ${filename}`, `    sha512: ${sha512}`, `    size: ${bytes.length}`, `path: ${filename}`, `sha512: ${sha512}`].join('\n')
  const key = crypto.createPrivateKey(process.env.XCAGI_UPDATE_ED25519_PRIVATE_KEY || '')
  if (key.asymmetricKeyType !== 'ed25519') throw Error('Release signing key required')
  fs.writeFileSync(path.join(dir, 'latest.yml'), `${body}\nsignature: ed25519:${crypto.sign(null, Buffer.from(body), key).toString('base64')}\n`)
} else if (action === 'serve') {
  const filename = path.basename(candidate)
  http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname.slice(1))
    if (!['latest.yml', filename].includes(name)) { res.writeHead(404).end(); return }
    const file = path.join(dir, name), size = fs.statSync(file).size
    const range = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || '')
    const start = range ? Number(range[1]) : 0, end = range && range[2] ? Number(range[2]) : size - 1
    if (start > end || end >= size) { res.writeHead(416).end(); return }
    res.writeHead(range ? 206 : 200, { 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes', ...(range ? { 'Content-Range': `bytes ${start}-${end}/${size}` } : {}) })
    fs.createReadStream(file, { start, end }).pipe(res)
  }).listen(18765, '127.0.0.1')
} else if (action === 'install') {
  const require = createRequire(path.join(root, 'frontend/package.json'))
  const { chromium } = require('@playwright/test')
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222')
  const page = browser.contexts()[0].pages().find(p => p.url().includes('127.0.0.1:17500'))
  if (!page) throw Error('Packaged app page missing')
  const events = []
  events.push({ stage: 'connected', at: new Date().toISOString() })
  try {
    const proof = await page.evaluate(async () => {
      const api = window.xcagiDesktop
      if (!api?.checkForUpdates || !api?.downloadUpdate || !api?.installUpdate) throw Error('Original app updater IPC incompatible')
      await api.checkForUpdates()
      await api.downloadUpdate()
      return await api.getUpdateStatus()
    })
    if (proof?.type !== 'update-downloaded') throw Error(`Update not downloaded: ${JSON.stringify(proof)}`)
    events.push({ stage: 'downloaded', at: new Date().toISOString() })
    fs.writeFileSync(path.join(dir, 'updater-download.json'), JSON.stringify(proof, null, 2))
    await page.screenshot({ path: path.join(dir, 'before-app-update.png') })
    await page.evaluate(() => window.xcagiDesktop.installUpdate()).catch(error => {
      if (!/closed|destroyed/.test(error.message)) throw error
    })
  } finally { fs.writeFileSync(path.join(dir, 'updater-driver.json'), JSON.stringify(events)); await browser.close() }
} else throw Error('Unknown lifecycle action')
