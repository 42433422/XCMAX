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
  if (fromEnv) return fromEnv
  try {
    const out = execFileSync(
      'security',
      ['find-identity', '-v', '-p', 'codesigning'],
      { encoding: 'utf8' }
    )
    const m = out.match(/"(Developer ID Application: [^"]+)"/)
    return m ? m[1] : ''
  } catch {
    return ''
  }
}

function codesign(target, identity, entitlements) {
  const args = ['--force', '--options', 'runtime', '--timestamp', '--sign', identity]
  if (entitlements) {
    args.push('--entitlements', entitlements)
  }
  args.push(target)
  execFileSync('codesign', args, { stdio: 'inherit' })
}

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return

  const appName = context.packager.appInfo.productFilename
  const appPath = path.join(context.appOutDir, `${appName}.app`)
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
    try {
      codesign(native, identity, null)
    } catch (err) {
      log(`native sign warn ${native}: ${err.message}`)
    }
  }
  codesign(backend, identity, entitlements)
  log(`backend entitlements applied (${natives.length} natives)`)
}
