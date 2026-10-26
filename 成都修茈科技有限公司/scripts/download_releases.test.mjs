// node --test scripts/download_releases.test.mjs — deterministic DOM, no browser/network.
import { readFileSync } from 'node:fs'
import { createContext, Script } from 'node:vm'
import { test } from 'node:test'
import assert from 'node:assert/strict'
const read = (file) => readFileSync(new URL('../' + file, import.meta.url), 'utf8')
const shared = read('release-data.js')
const version = '2.3.4.5', sha = 'a'.repeat(40), digest = 'b'.repeat(64)
const root = 'https://xiu-ci.com/xcagi-v' + version
const identity = { version, git_sha: sha, release_id: 'release-' + sha }
const pointer = { ...identity, download_version: version, release_ready: true, manifest_url: root + '/manifest.json', android_version: '1.2.3.0' }
const artifact = (filename) => ({ filename, url: root + '/enterprise/' + filename, sha256: digest, size: 1048576 })
const manifest = () => ({ ...identity, schema: 'xcagi.download_manifest/v1', release_ready: true,
  channels: { official_download: { enterprise: {
    win: artifact(`XCAGI-Enterprise-Setup-${version}-x64.exe`),
    mac: [artifact(`XCAGI-Enterprise-${version}-mac-arm64.dmg`)],
  } } } })
const interim = () => {
  const filename = `XCAGI-Enterprise-Setup-${version}-x64-unsigned.exe`
  return { schema: 'xcagi.windows_interim_release/v1', version, git_sha: sha, download_allowed: true,
    signature_status: 'unsigned', stable_auto_update: false, risk_acceptance: { expires_at: '2999-01-01T00:00:00Z' },
    artifact: { ...artifact(filename), url: `${root}/enterprise/${sha}/${digest}/${filename}`, platform: 'windows', arch: 'x64' } }
}
function element() {
  return { children: [], attributes: {}, events: {}, className: '', ownText: '', hidden: false,
    classList: { toggle() {} },
    get textContent() { return this.ownText + this.children.map((child) => typeof child === 'string' ? child : child.textContent).join('') },
    set textContent(value) { this.ownText = String(value); this.children = [] },
    appendChild(child) { this.children.push(child) }, append(...children) { this.children.push(...children) },
    replaceChildren(...children) { this.ownText = ''; this.children = children },
    setAttribute(name, value) { this.attributes[name] = value },
    addEventListener(name, fn) { this.events[name] = fn },
  }
}
async function render(page, files = {}, userAgent = '') {
  const nodes = new Map(), calls = []
  const context = { URLSearchParams, navigator: { userAgent }, location: { hash: '', search: '' },
    document: { createElement: element, getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id) } },
    fetch: async (url) => { calls.push(url); if (files[url] instanceof Error) throw files[url]
      return { ok: url in files, headers: { get: () => 'application/json' }, json: async () => files[url] } },
  }
  context.window = context
  const sandbox = createContext(context)
  new Script(shared).runInContext(sandbox)
  const html = read(page + '.html')
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    if (match[1].trim()) new Script(match[1]).runInContext(sandbox)
  }
  await new Promise(setImmediate)
  return { node: (id) => nodes.get(id), calls, api: context.XCReleaseData }
}
const historyFiles = (rows) => ({ '/download-release.json': pointer,
  '/data/release-history.json': { schema: 'xcagi.release_history.public/v1', release_history: rows },
  '/data/release-presentation.json': { phases: [{ title: 'Phase', range: 'History', description: 'Context' }] },
})
test('history counts derive from deduplicated SSOT records, not stale pointer history or constants', async () => {
  for (const count of [0, 1, 13, 16, 17, 21]) {
    const rows = Array.from({ length: count }, (_, i) => ({ version: `3.0.${i}`, kind: i % 2 ? 'milestone' : 'release', notes: ['Change'] }))
    const files = historyFiles([...rows, ...rows.slice(0, 1), null, { version: '' }])
    files['/download-release.json'] = { ...pointer, release_history: [{ version: 'legacy-pointer-only' }] }
    const { node } = await render('download-releases', files)
    assert.equal(node('history-count').textContent, String(count))
    assert.equal(node('milestone-count').textContent, String(Math.floor(count / 2)))
    assert.equal(node('phase-count').textContent, '1')
    assert.equal(node('release-list').children.length, count)
    assert.equal(node('summary-version').textContent, 'v' + version)
    assert.match(node('summary-status').textContent, /未开放|待核验/)
    assert.doesNotMatch(node('release-list').textContent, /legacy-pointer-only/)
  }
})
test('summary selects current pointer, never first history item or a future candidate', async () => {
  const rows = [{ version: '99.0.0.0', publication_state: 'candidate' }, { version, date: '2026-10-16', publication_state: 'published' }]
  for (let repeat = 0; repeat < 2; repeat++) {
    const { node } = await render('download-releases', historyFiles(rows))
    assert.equal(node('summary-version').textContent, 'v' + version)
    assert.equal(node('summary-date').textContent, '2026-10-16')
    assert.match(node('release-list').textContent, /候选（未晋升）/)
    assert.match(node('release-list').textContent, /历史已发布（不代表当前可下载）/)
    assert.doesNotMatch(node('release-list').children[0].className, /is-current/)
    assert.match(node('release-list').children[1].className, /is-current/)
  }
})
test('missing historical projection stays unknown while current pointer remains independent', async () => {
  for (const projection of [null, { release_history: [] }, new Error('offline')]) {
    const files = { ...historyFiles([]), '/data/release-history.json': projection }
    const { node } = await render('download-releases', files)
    assert.equal(node('history-count').textContent, '—')
    assert.match(node('release-list').textContent, /未能读取/)
    assert.equal(node('summary-version').textContent, 'v' + version)
  }
})
test('missing pointers and manifest 404 never advertise stable readiness', async () => {
  for (const files of [{}, { '/download-release.json': new Error('offline') }, historyFiles([{ version }])]) {
    const { node } = await render('download-releases', files)
    assert.doesNotMatch(node('summary-status').textContent, /稳定版可下载/)
    assert.doesNotMatch(node('summary-changes').textContent, /：可下载/)
  }
})
test('shared artifact validation fails closed for mismatches, missing sizes, and wrong architectures', async () => {
  const { api } = await render('download', {})
  assert.ok(api.view(pointer, manifest()).entry('mac', 'arm64'))
  assert.equal(api.view(pointer, manifest()).entry('mac', 'x64'), null)
  for (const patch of [{ release_ready: false }, { version_lock: '99.0.0.0' }, { release_id: '' }, { git_sha: 'c'.repeat(40) }]) {
    assert.equal(api.view({ ...pointer, ...patch }, manifest()).entry('mac', 'arm64'), null)
  }
  for (const patch of [{ size: 0 }, { size: undefined }, { sha256: '' }, { arch: 'x64' }, { url: 'https://evil.test/download' }]) {
    const data = manifest(); Object.assign(data.channels.official_download.enterprise.mac[0], patch)
    assert.equal(api.view(pointer, data).entry('mac', 'arm64'), null)
  }
  const immutable = manifest(), row = immutable.channels.official_download.enterprise.mac[0]
  row.url = `${root}/builds/${sha}/enterprise/${row.filename}`
  assert.ok(api.view(pointer, immutable).entry('mac', 'arm64'))
  row.url = row.url.replace(sha, 'c'.repeat(40))
  assert.equal(api.view(pointer, immutable).entry('mac', 'arm64'), null)
})
test('Windows interim is validated identically on both pages and stays non-OTA', async () => {
  const rows = [{ version, notes: [] }]
  const files = { ...historyFiles(rows), '/download-windows-hotfix.json': interim() }
  const { node } = await render('download-releases', files)
  assert.match(node('summary-changes').textContent, /Windows x64.*可下载 · 临时手动下载·不进入自动更新/)
  assert.match(node('summary-changes').textContent, /macOS Apple Silicon.*未开放/)
  const download = await render('download', files)
  assert.equal(download.node('download-list').children[0].href, interim().artifact.url)
  assert.match(download.node('download-note').textContent, /不进入稳定自动更新/)
  for (const patch of [{ stable_auto_update: true }, { version: '99.0.0.0' }, { risk_acceptance: { expires_at: '2000-01-01' } }]) {
    const bad = { ...interim(), ...patch }
    assert.equal(download.api.view(pointer, null, bad).interim(), null)
  }
  const bad = interim(); bad.artifact.url = 'https://evil.test/installer.exe'
  assert.equal(download.api.view(pointer, null, bad).interim(), null)
})
test('Android version stays experimental, missing artifact does not create a guessed download; tabs repeat safely', async () => {
  const { node } = await render('download', { '/download-release.json': pointer }, 'Android')
  for (let repeat = 0; repeat < 3; repeat++) {
    node('android-tab').events.click()
    assert.match(node('version').textContent, /Android 实验版本 1.2.3.0/)
    assert.equal(node('download-list').children.length, 1)
    assert.equal(node('download-list').children[0].href, undefined)
    assert.equal(node('download-list').children[0].attributes['aria-disabled'], 'true')
    node('desktop-tab').events.click()
    assert.equal(node('download-list').children.length, 3)
  }
})
test('manifest_url is authoritative and untrusted origins are not requested', async () => {
  const custom = 'https://xiu-ci.com/releases/by-id/manifest.json'
  const files = { '/download-release.json': { ...pointer, manifest_url: custom }, [custom]: manifest() }
  const good = await render('download', files)
  assert.ok(good.calls.includes(custom))
  assert.equal(good.node('download-list').children[1].href, manifest().channels.official_download.enterprise.mac[0].url)
  files['/download-release.json'] = { ...pointer, manifest_url: 'https://evil.test/manifest.json' }
  const bad = await render('download', files)
  assert.ok(!bad.calls.includes('https://evil.test/manifest.json'))
  assert.ok(bad.node('download-list').children.every((el) => !el.href))
})

test('the checked-in generated projection renders every canonical record without a UI snapshot', async () => {
  const projection = JSON.parse(read('data/release-history.json'))
  const { node, api } = await render('download-releases', { ...historyFiles([]), '/data/release-history.json': projection })
  const rows = api.history(projection.release_history)
  assert.equal(node('history-count').textContent, String(rows.length))
  assert.equal(node('release-list').children.length, rows.length)
  for (const row of rows) assert.ok(node('release-list').textContent.includes('v' + row.version))
})

test('a disclosed test-only Windows artifact has its own identity and leaves stable and Mac unchanged', async () => {
  const testVersion = '2.3.4.6', testRoot = 'https://xiu-ci.com/xcagi-v' + testVersion
  const hotfix = interim(), filename = `XCAGI-Enterprise-Setup-${testVersion}-x64-unsigned.exe`
  Object.assign(hotfix, { version: testVersion, release: { version: testVersion, test_only: true, notes: ['ETL not accepted', 'Original fifteen scenarios remain open'] } })
  Object.assign(hotfix.artifact, { filename, url: `${testRoot}/enterprise/${sha}/${digest}/${filename}` })
  const files = { ...historyFiles([{ version, notes: [] }]), [root + '/manifest.json']: manifest(), '/download-windows-hotfix.json': hotfix }
  for (const page of ['download', 'download-releases']) {
    const { node, api } = await render(page, files)
    assert.equal(api.view(pointer, manifest(), hotfix).platform('win').version, testVersion)
    assert.equal(api.view(pointer, manifest(), hotfix).platform('mac', 'arm64').version, version)
    const text = node(page === 'download' ? 'download-note' : 'summary-changes').textContent
    assert.match(text, /测试版/); assert.match(text, /ETL not accepted/); assert.match(text, /fifteen scenarios/)
    assert.equal(api.view(pointer, manifest(), { ...hotfix, release: { ...hotfix.release, test_only: false } }).interim(), null)
    for (const patch of [{ version }, { notes: [] }]) {
      assert.equal(api.view(pointer, manifest(), { ...hotfix, release: { ...hotfix.release, ...patch } }).interim(), null)
    }
  }
  const download = await render('download', files)
  assert.equal(download.node('download-list').children[0].href, hotfix.artifact.url)
  assert.match(download.node('download-list').children[0].textContent, /测试版/)
  assert.equal(download.node('download-list').children[1].href, manifest().channels.official_download.enterprise.mac[0].url)
})
