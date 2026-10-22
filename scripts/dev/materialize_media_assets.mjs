/** Restore product-media URLs from the shared, checksum-pinned source registry. */
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const SITE = '成都修茈科技有限公司'
const TARGETS = {
  frontend: ['FHD/frontend/public/'],
  market: [`${SITE}/MODstore_deploy/market/public/`],
  marketing: [`${SITE}/corp-butler/`, `${SITE}/assets/optimized/`, `${SITE}/marketing-assets/xc-brand-film/assets/`],
  appstore: ['appstore-screenshots/live/'],
}
const SOURCES = ['FHD/frontend/public/', `${SITE}/assets/`, 'appstore-screenshots/2.3.3-accurate-metadata/']
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex')

function inside(root, relative) {
  if (!relative || relative.includes('\\') || relative.startsWith('/') || relative.split('/').some((p) => !p || p === '.' || p === '..')) {
    throw new Error(`Unsafe media path: ${relative}`)
  }
  const result = path.resolve(root, relative)
  const targetStat = fs.lstatSync(result, { throwIfNoEntry: false })
  let ancestor = result
  while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor)
  const actual = path.relative(fs.realpathSync(root), fs.realpathSync(ancestor))
  if (actual === '..' || actual.startsWith(`..${path.sep}`) || path.isAbsolute(actual) || targetStat?.isSymbolicLink()) {
    throw new Error(`Media path escapes its root or is a symlink: ${relative}`)
  }
  return result
}

export function verifyMediaAssets(scope = 'all', root = ROOT) {
  if (scope !== 'all' && !Object.hasOwn(TARGETS, scope)) throw new Error(`Unknown media scope: ${scope}`)
  const data = JSON.parse(fs.readFileSync(path.join(root, 'config/media-aliases.json'), 'utf8'))
  if (data.schema !== 'xcmax.media-aliases/v1') throw new Error('Unsupported media registry')
  const verified = []
  for (const [target, entry] of Object.entries(data.aliases)) {
    if (!TARGETS[entry.scope]?.some((prefix) => target.startsWith(prefix)) || !SOURCES.some((prefix) => entry.source.startsWith(prefix)) || Object.hasOwn(data.aliases, entry.source)) {
      throw new Error(`Unregistered or chained media source/target: ${target}`)
    }
    if (scope !== 'all' && scope !== entry.scope) continue
    const source = inside(root, entry.source)
    const destination = inside(root, target)
    const bytes = fs.readFileSync(source)
    if (bytes.length !== entry.size || sha(bytes) !== entry.sha256) throw new Error(`Canonical media checksum mismatch: ${entry.source}`)
    verified.push({ source, destination, entry })
  }
  return verified
}

export function materializeMediaAssets(scope = 'all', root = ROOT) {
  const sources = verifyMediaAssets(scope, root) // Verify every input before writing any output.
  for (const { source, destination, entry } of sources) {
    if (fs.existsSync(destination) && sha(fs.readFileSync(destination)) === entry.sha256) continue
    fs.mkdirSync(path.dirname(destination), { recursive: true })
    const temporary = `${destination}.media-${process.pid}-${Math.random().toString(16).slice(2)}`
    try {
      fs.copyFileSync(source, temporary, fs.constants.COPYFILE_EXCL)
      if (sha(fs.readFileSync(temporary)) !== entry.sha256) throw new Error(`Media changed during reconstruction: ${source}`)
      fs.renameSync(temporary, destination)
    } finally {
      fs.rmSync(temporary, { force: true })
    }
  }
  return sources.length
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const check = process.argv.includes('--check')
    const scope = process.argv.slice(2).find((arg) => arg !== '--check') || 'all'
    const count = check ? verifyMediaAssets(scope).length : materializeMediaAssets(scope)
    console.log(`[media-assets] ${check ? 'verified' : 'materialized'} ${count} aliases (${scope})`)
  } catch (error) {
    console.error(`[media-assets] FAIL: ${error.message}`)
    process.exitCode = 1
  }
}
