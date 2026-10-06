import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { runInThisContext } from 'node:vm'
import { afterEach, expect, it, vi } from 'vitest'

const html = readFileSync(join(process.cwd(), '../../成都修茈科技有限公司/download.html'), 'utf8')
const script = html.split('<script>')[1].split('</script>')[0]
const sha = 'a'.repeat(40)
const digest = 'b'.repeat(64)
const root = 'https://xiu-ci.com/xcagi-v1.0.0.5'
const identity = { version: '1.0.0.5', git_sha: sha, release_id: `xcagi-1.0.0.5-${sha}` }
const pointer = (ready: boolean, extra = {}) => ({ ...identity, download_version: '1.0.0.5', release_ready: ready, release_root: root, ...extra })
const entry = (filename: string) => ({ filename, url: `${root}/enterprise/${filename}`, sha256: digest, size: 1048576 })
const manifest = (macs: string[]) => ({
  ...identity, schema: 'xcagi.download_manifest/v1', release_ready: true,
  channels: { official_download: { enterprise: {
    win: entry('XCAGI-Enterprise-Setup-1.0.0.5-x64.exe'),
    mac: macs.map((arch) => entry(`XCAGI-Enterprise-1.0.0.5-mac-${arch}.dmg`)),
  } } },
})
const interimName = 'XCAGI-Enterprise-Setup-1.0.0.5-x64-unsigned.exe'
const interim = (url = `${root}/enterprise/${sha}/${digest}/${interimName}`) => ({
  schema: 'xcagi.windows_interim_release/v1', version: '1.0.0.5', git_sha: sha, download_allowed: true,
  signature_status: 'unsigned', stable_auto_update: false, risk_acceptance: { expires_at: '2999-01-01T00:00:00Z' },
  artifact: { platform: 'windows', arch: 'x64', filename: interimName, sha256: digest, size: 1048576, url },
})

async function open(files: Record<string, unknown>, search = '') {
  window.history.replaceState(null, '', `/download${search}`)
  const page = new DOMParser().parseFromString(html, 'text/html').body
  document.body.replaceChildren(...Array.from(page.childNodes, (node) => document.importNode(node, true)))
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: url in files, headers: { get: () => 'application/json' }, json: async () => files[url],
  })))
  runInThisContext(script)
  await new Promise((resolve) => setTimeout(resolve))
  const links = Array.from(document.querySelectorAll('.download-item'))
  return Object.fromEntries(links.map((link) => [link.querySelector('strong')?.textContent, link.getAttribute('href')]))
}

afterEach(() => vi.unstubAllGlobals())
it('offers stable installers only when the pointer and manifest agree on a ready release', async () => {
  const stable = { [`${root}/manifest.json`]: manifest(['arm64']) }
  expect(await open({ ...stable, '/download-release.json': pointer(true) })).toEqual({
    'Windows 64 位': `${root}/enterprise/XCAGI-Enterprise-Setup-1.0.0.5-x64.exe`,
    'macOS · Apple Silicon': `${root}/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg`, 'macOS · Intel': null,
  })
  expect(document.getElementById('pending')?.hidden).toBe(false)
  for (const release of [pointer(false), pointer(true, { git_sha: 'c'.repeat(40) })]) {
    expect(Object.values(await open({ ...stable, '/download-release.json': release }))).toEqual([null, null, null])
    expect(document.getElementById('pending')?.hidden).toBe(false)
  }
})

it('never hands an Intel Mac the Apple Silicon image', async () => {
  const files = (macs: string[]) => ({ '/download-release.json': pointer(true), [`${root}/manifest.json`]: manifest(macs) })
  const armOnly = await open(files(['arm64']))
  expect([armOnly['macOS · Apple Silicon'], armOnly['macOS · Intel']]).toEqual([`${root}/enterprise/XCAGI-Enterprise-1.0.0.5-mac-arm64.dmg`, null])
  expect((await open(files(['arm64', 'x64']), '?macArch=x64'))['macOS · Intel']).toBe(`${root}/enterprise/XCAGI-Enterprise-1.0.0.5-mac-x64.dmg`)
})

it('lists the Windows interim installer only at the path the release workflow publishes', async () => {
  const files = { '/download-release.json': pointer(false) }
  const valid = await open({ ...files, '/download-windows-hotfix.json': interim() })
  expect(valid['Windows 64 位 · 临时交付 v1.0.0.5']).toBe(interim().artifact.url)
  expect(document.getElementById('download-note')?.textContent).toContain('macOS 稳定包暂未开放')
  const forged = await open({ ...files, '/download-windows-hotfix.json': interim(`https://example.com/${interimName}`) })
  expect(forged['Windows 64 位']).toBeNull()
})
