#!/usr/bin/env node
/**
 * 补全当前平台缺失的 npm optional native bindings。
 * 常见于 node_modules 从 Windows 拷贝到 macOS，或 npm optional 依赖未安装。
 *
 * 优先使用 npm install（若可用）；否则从 npmmirror 拉取 tarball 解压。
 *
 * Usage:
 *   node scripts/install-native-bindings.mjs
 *   npm run install:native
 */

import { spawnSync } from 'node:child_process'
import { mkdir, mkdtemp, rm, cp } from 'node:fs/promises'
import { readdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..')
const REGISTRY = process.env.NPM_REGISTRY || 'https://registry.npmmirror.com'

/** @type {Record<string, Array<{ name: string; version: string }>>} */
const PLATFORM_PACKAGES = {
  'darwin-arm64': [
    { name: '@rolldown/binding-darwin-arm64', version: '1.0.0-rc.17' },
    { name: '@rollup/rollup-darwin-arm64', version: '4.60.2' },
    { name: '@esbuild/darwin-arm64', version: '0.21.5' },
  ],
  'darwin-x64': [
    { name: '@rolldown/binding-darwin-x64', version: '1.0.0-rc.17' },
    { name: '@rollup/rollup-darwin-x64', version: '4.60.2' },
    { name: '@esbuild/darwin-x64', version: '0.21.5' },
  ],
  'linux-x64': [
    { name: '@rolldown/binding-linux-x64-gnu', version: '1.0.0-rc.17' },
    { name: '@rollup/rollup-linux-x64-gnu', version: '4.60.2' },
    { name: '@esbuild/linux-x64', version: '0.21.5' },
  ],
  'win32-x64': [
    { name: '@rolldown/binding-win32-x64-msvc', version: '1.0.0-rc.17' },
    { name: '@rollup/rollup-win32-x64-msvc', version: '4.60.2' },
    { name: '@esbuild/win32-x64', version: '0.21.5' },
  ],
}

function detectPlatformKey() {
  const { platform, arch } = process
  if (platform === 'darwin') return arch === 'arm64' ? 'darwin-arm64' : 'darwin-x64'
  if (platform === 'linux') return 'linux-x64'
  if (platform === 'win32') return 'win32-x64'
  return `${platform}-${arch}`
}

function pkgDir(packageName) {
  if (packageName.startsWith('@')) {
    const [scope, base] = packageName.split('/')
    return join(ROOT, 'node_modules', scope, base)
  }
  return join(ROOT, 'node_modules', packageName)
}

function dirHasBinding(dir) {
  try {
    const names = readdirSync(dir)
    if (names.some((n) => n.endsWith('.node') || n === 'esbuild' || n === 'esbuild.exe')) return true
    const binDir = join(dir, 'bin')
    try {
      const binNames = readdirSync(binDir)
      if (binNames.some((n) => n === 'esbuild' || n === 'esbuild.exe')) return true
    } catch {
      /* no bin */
    }
    return false
  } catch {
    return false
  }
}

async function downloadTarball(name, version, destDir) {
  const encoded = name.replace('/', '%2F')
  const short = name.split('/').pop()
  const url = `${REGISTRY}/${encoded}/-/${short}-${version}.tgz`
  const tmpRoot = await mkdtemp(join(tmpdir(), 'native-bind-'))
  const tgzPath = join(tmpRoot, 'pkg.tgz')
  const extractDir = join(tmpRoot, 'extract')

  console.log(`  fetch ${name}@${version}`)
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  const buf = Buffer.from(await res.arrayBuffer())
  const { writeFile } = await import('node:fs/promises')
  await writeFile(tgzPath, buf)

  await mkdir(extractDir, { recursive: true })
  const tar = spawnSync('tar', ['-xzf', tgzPath, '-C', extractDir], { encoding: 'utf8' })
  if (tar.status !== 0) throw new Error(tar.stderr || 'tar extract failed')

  await mkdir(destDir, { recursive: true })
  await cp(join(extractDir, 'package'), destDir, { recursive: true, force: true })
  await rm(tmpRoot, { recursive: true, force: true })
}

function installViaNpm(packages) {
  const specs = packages.map((p) => `${p.name}@${p.version}`)
  const r = spawnSync('npm', ['install', '--no-save', '--include=optional', ...specs], {
    cwd: ROOT,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  })
  return r.status === 0 && !r.error
}

async function main() {
  const key = detectPlatformKey()
  const packages = PLATFORM_PACKAGES[key]
  if (!packages) {
    console.error(`Unsupported platform key: ${key}`)
    process.exit(1)
  }

  console.log(`[install-native-bindings] platform=${key}`)

  const missing = packages.filter((p) => !dirHasBinding(pkgDir(p.name)))
  if (!missing.length) {
    console.log('All native bindings already present.')
    return
  }

  console.log(`Missing ${missing.length} binding(s): ${missing.map((p) => p.name).join(', ')}`)

  if (!installViaNpm(missing)) {
    console.log('npm unavailable or failed; falling back to tarball download…')
    for (const p of missing) {
      const dir = pkgDir(p.name)
      if (dirHasBinding(dir)) continue
      await downloadTarball(p.name, p.version, dir)
    }
  }

  const stillMissing = packages.filter((p) => !dirHasBinding(pkgDir(p.name))).map((p) => p.name)
  if (stillMissing.length) {
    console.error('Still missing:', stillMissing.join(', '))
    console.error('Try: cd market && rm -rf node_modules && npm ci && npm run install:native')
    process.exit(1)
  }
  console.log('Native bindings OK.')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
