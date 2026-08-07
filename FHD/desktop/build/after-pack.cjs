/**
 * electron-builder afterPack: clean macOS metadata and ensure the PyInstaller
 * backend carries full Hardened Runtime entitlements before final signing.
 */
const { execFileSync, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

function log(msg) {
  console.log(`[after-pack] ${msg}`)
}

function resolveIdentity() {
  const fromEnv = (
    process.env.CSC_NAME ||
    process.env.CSC_IDENTITY ||
    process.env.APPLE_IDENTITY ||
    ''
  ).trim()
  if (/^[0-9a-f]{40}$/i.test(fromEnv)) return fromEnv
  try {
    const out = execFileSync(
      'security',
      ['find-identity', '-v', '-p', 'codesigning'],
      { encoding: 'utf8' }
    )
    if (fromEnv) {
      // electron-builder 26 expects CSC_NAME without the certificate-class
      // prefix, while codesign needs an unambiguous identity when the same
      // owner also has an iPhone Distribution certificate. Resolve the exact
      // Developer ID entry to its SHA-1 fingerprint for custom nested signing.
      const fullName = fromEnv.startsWith('Developer ID Application: ')
        ? fromEnv
        : `Developer ID Application: ${fromEnv}`
      for (const line of out.split(/\r?\n/)) {
        const match = line.match(/\b([0-9A-F]{40})\s+"([^"]+)"/i)
        if (match && match[2] === fullName) return match[1]
      }
      return fullName
    }
    const m = out.match(/"(Developer ID Application: [^"]+)"/)
    return m ? m[1] : ''
  } catch {
    if (!fromEnv) return ''
    return fromEnv.startsWith('Developer ID Application: ')
      ? fromEnv
      : `Developer ID Application: ${fromEnv}`
  }
}

function codesign(target, identity, entitlements) {
  const args = ['--force', '--options', 'runtime', '--timestamp', '--sign', identity]
  if (entitlements) {
    args.push('--entitlements', entitlements)
  }
  args.push(target)
  try {
    execFileSync('codesign', args, { encoding: 'utf8', stdio: 'pipe' })
  } catch (err) {
    if (err.stdout) process.stdout.write(String(err.stdout))
    if (err.stderr) process.stderr.write(String(err.stderr))
    throw err
  }
}

function assertBundledVueDist(root, platform) {
  const candidates =
    platform === 'darwin'
      ? [path.join(root, 'Contents/Resources/backend/_internal/templates/vue-dist')]
      : [path.join(root, 'resources/backend/_internal/templates/vue-dist')]
  let vueDist = ''
  for (const c of candidates) {
    if (fs.existsSync(path.join(c, 'index.html'))) {
      vueDist = c
      break
    }
  }
  if (!vueDist) {
    throw new Error(
      `[after-pack] bundled vue-dist/index.html missing under ${root} — desktop would show no page`
    )
  }
  const jsDir = path.join(vueDist, 'assets/js')
  const jsCount = fs.existsSync(jsDir)
    ? fs.readdirSync(jsDir).filter((n) => n.endsWith('.js')).length
    : 0
  if (jsCount < 1) {
    throw new Error(`[after-pack] ${jsDir} has no *.js — desktop would show no page`)
  }
  log(`vue-dist gate ok (${jsCount} js): ${vueDist}`)
}

exports.default = async function afterPack(context) {
  const appName = context.packager.appInfo.productFilename
  const probeRoot =
    context.electronPlatformName === 'darwin'
      ? path.join(context.appOutDir, `${appName}.app`)
      : context.appOutDir
  assertBundledVueDist(probeRoot, context.electronPlatformName)

  if (context.electronPlatformName !== 'darwin') return

  const appPath = probeRoot
  // Cached Electron archives may also carry com.apple.provenance/quarantine.
  // None of these attributes belongs in a distributable app bundle, and codesign
  // rejects inherited Finder/resource metadata before the final seal is written.
  spawnSync('/usr/bin/xattr', ['-cr', appPath], { stdio: 'ignore' })
  const backend = path.join(appPath, 'Contents/Resources/backend/xcagi-backend')
  if (!fs.existsSync(backend)) {
    log(`backend missing, skip: ${backend}`)
    return
  }

  const entitlements = path.join(context.packager.projectDir, 'build/entitlements.mac.plist')
  if (!fs.existsSync(entitlements)) {
    log(`entitlements missing, skip: ${entitlements}`)
    return
  }

  const identity = resolveIdentity()
  if (!identity) {
    log('no Developer ID identity; skip backend entitlements re-sign')
    return
  }

  log(`re-sign backend with entitlements: ${backend}`)
  const backendDir = path.dirname(backend)
  const natives = []
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name)
      if (ent.isDirectory()) walk(p)
      else if (/\.(so|dylib)$/i.test(ent.name)) natives.push(p)
    }
  }
  walk(backendDir)
  for (const native of natives) {
    codesign(native, identity, null)
  }
  codesign(backend, identity, entitlements)
  log(`backend entitlements applied (${natives.length} natives)`)
}
