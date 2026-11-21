// Reproduce the reviewed renderer subset and sprite atlas; never fetches code at build time.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'

const pin = '4dd14d612fd37d89ffbbc977959f572395c4eec8'
const upstream = path.resolve(process.argv[2] || '')
const out = path.dirname(fileURLToPath(import.meta.url))
if (!process.argv[2] || execFileSync('git', ['rev-parse', 'HEAD'], { cwd: upstream, encoding: 'utf8' }).trim() !== pin) {
  throw new Error(`Pass a clean pixel-agents checkout at ${pin}`)
}
if (execFileSync('git', ['status', '--porcelain'], { cwd: upstream, encoding: 'utf8' }).trim()) {
  throw new Error('Refusing to vendor a dirty upstream checkout')
}
const require = createRequire(path.resolve(out, '../../frontend/package.json'))
const { build } = require('esbuild')
const { PNG } = require('pngjs')
const roots = [
  'webview-ui/src/office/engine/officeState.ts', 'webview-ui/src/office/engine/renderer.ts',
  'webview-ui/src/office/engine/gameLoop.ts', 'webview-ui/src/office/floorTiles.ts',
  'webview-ui/src/office/wallTiles.ts', 'webview-ui/src/office/toolUtils.ts',
  'webview-ui/src/office/sprites/spriteData.ts', 'webview-ui/src/office/layout/furnitureCatalog.ts',
  'core/src/assets/characterSheet.ts',
]
const files = new Map()
function copy(relative) {
  if (files.has(relative)) return
  const original = fs.readFileSync(path.join(upstream, relative), 'utf8')
  let text = original
  // Only the pure context ratio is used by OfficeState. Drop the React card hook/store.
  if (relative === 'webview-ui/src/office/contextGauge.ts') {
    text = text.replace("import { useSyncExternalStore } from 'react';\n", '')
    text = text.slice(0, text.indexOf('// Each agent')).trimEnd() + '\n'
  }
  files.set(relative, { sha256: createHash('sha256').update(original).digest('hex'), modified: text !== original })
  const target = path.join(out, relative)
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.writeFileSync(target, text)
  if (relative.endsWith('.json')) return
  for (const [, spec] of text.matchAll(/(?:from\s+|import\s*)['"]([^'"]+)['"]/g)) {
    if (!spec.startsWith('.')) throw new Error(`Unexpected runtime dependency ${spec} in ${relative}`)
    const candidate = path.resolve(upstream, path.dirname(relative), spec)
    const resolved = [candidate, candidate.replace(/\.js$/, '.ts'), candidate.replace(/\.js$/, '.tsx'), `${candidate}/index.ts`]
      .find(file => fs.existsSync(file) && fs.statSync(file).isFile())
    if (!resolved) throw new Error(`Missing ${spec} from ${relative}`)
    copy(path.relative(upstream, resolved))
  }
}
roots.forEach(copy)
fs.copyFileSync(path.join(upstream, 'LICENSE'), path.join(out, 'LICENSE'))

// Use the upstream character compositor and manifest flattener unchanged at import time.
const built = await build({
  stdin: {
    contents: `export { CharacterRenderer } from './webview-ui/src/characters/renderer.ts';
export { decodeWardrobe, parseWardrobeManifest } from './webview-ui/src/characters/wardrobe.ts';
export { EYE_FOLDERS } from './webview-ui/src/characters/slots.ts';
export { DEFAULT_CHARACTER_PROFILES } from './core/src/defaultCharacterProfiles.ts';
export { flattenManifest } from './core/src/assets/manifestUtils.ts';`,
    resolveDir: upstream, loader: 'ts',
  },
  bundle: true, write: false, format: 'cjs', platform: 'node',
})
const module = { exports: {} }
new Function('module', 'exports', built.outputFiles[0].text)(module, module.exports)
const { CharacterRenderer, decodeWardrobe, parseWardrobeManifest, EYE_FOLDERS, DEFAULT_CHARACTER_PROFILES, flattenManifest } = module.exports
const art = path.join(upstream, 'webview-ui/src/characters/art')
const wardrobeFiles = new Map(fs.readdirSync(art, { recursive: true, encoding: 'utf8' }).filter(f => f.endsWith('.png')).map(f => {
  const png = PNG.sync.read(fs.readFileSync(path.join(art, f)))
  return [f.split(path.sep).join('/').replace(/\.png$/, ''), { width: png.width, height: png.height, data: new Uint8ClampedArray(png.data) }]
}))
const wardrobe = decodeWardrobe(parseWardrobeManifest(JSON.parse(fs.readFileSync(path.join(art, 'wardrobe.json'), 'utf8'))), wardrobeFiles, EYE_FOLDERS)
const renderer = new CharacterRenderer(wardrobe)
const sprites = DEFAULT_CHARACTER_PROFILES.map((profile, i) => ({ id: `character-${i}`, width: 128, height: 96, data: renderer.sheet(profile) }))
const assetRoot = path.join(upstream, 'webview-ui/public/assets')
const catalog = []
for (const folder of ['DESK', 'WOODEN_CHAIR', 'PC', 'PLANT', 'BOOKSHELF', 'WHITEBOARD']) {
  const dir = path.join(assetRoot, 'furniture', folder)
  const m = JSON.parse(fs.readFileSync(path.join(dir, 'manifest.json'), 'utf8'))
  const inherited = { groupId: m.id, name: m.name, category: m.category, canPlaceOnWalls: m.canPlaceOnWalls, canPlaceOnSurfaces: m.canPlaceOnSurfaces, backgroundTiles: m.backgroundTiles }
  const assets = m.type === 'group' ? flattenManifest(m, inherited) : [{ ...m, label: m.name, file: m.file || `${m.id}.png`, isDesk: m.category === 'desks' }]
  for (const item of assets) {
    catalog.push(item)
    sprites.push({ id: item.id, ...PNG.sync.read(fs.readFileSync(path.join(dir, item.file))) })
  }
}
for (const [id, file] of [['floor', 'floors/floor_0.png'], ['wall', 'walls/wall_0.png']]) {
  sprites.push({ id, ...PNG.sync.read(fs.readFileSync(path.join(assetRoot, file))) })
}
const width = 512
let x = 0, y = 0, rowHeight = 0
const rects = {}
for (const s of sprites) {
  if (x + s.width > width) { x = 0; y += rowHeight; rowHeight = 0 }
  rects[s.id] = { x, y, width: s.width, height: s.height }
  x += s.width
  rowHeight = Math.max(rowHeight, s.height)
}
const atlas = new PNG({ width, height: y + rowHeight })
for (const s of sprites) {
  const rect = rects[s.id]
  for (let row = 0; row < s.height; row++) {
    atlas.data.set(s.data.subarray(row * s.width * 4, (row + 1) * s.width * 4), ((rect.y + row) * width + rect.x) * 4)
  }
}
fs.writeFileSync(path.join(out, 'atlas.png'), PNG.sync.write(atlas, { filterType: 0, deflateLevel: 9, deflateStrategy: 0 }))
fs.writeFileSync(path.join(out, 'atlas.json'), JSON.stringify({ catalog, rects }))
fs.writeFileSync(path.join(out, 'upstream.json'), JSON.stringify({ repository: 'https://github.com/pixel-agents-hq/pixel-agents', version: 'v1.6.0', commit: pin, files: Object.fromEntries([...files.entries()].sort()) }, null, 2) + '\n')
console.log(`Vendored ${files.size} source files; sprite atlas ${fs.statSync(path.join(out, 'atlas.png')).size} bytes`)
