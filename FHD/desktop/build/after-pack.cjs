/**
 * electron-builder afterPack: remove macOS Finder/resource-fork metadata before
 * Developer ID signing. These xattrs are not application data and codesign
 * rejects bundles containing them as "similar detritus not allowed".
 */
const path = require('node:path')
const { spawnSync } = require('node:child_process')

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'darwin') return

  const appName = context.packager.appInfo.productFilename
  const appPath = path.join(context.appOutDir, `${appName}.app`)
  // Cached Electron archives may also carry com.apple.provenance/quarantine.
  // None of these attributes belongs in a distributable app bundle, and codesign
  // rejects inherited Finder/resource metadata before the final seal is written.
  spawnSync('/usr/bin/xattr', ['-cr', appPath], { stdio: 'ignore' })
}
