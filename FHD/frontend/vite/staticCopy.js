import fs from 'fs'
import path from 'path'

export function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true })
  }
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath)
    } else {
      fs.copyFileSync(srcPath, destPath)
    }
  }
}

/** SSOT: FHD/mods；导出副本 FHD/XCAGI/mods（见 scripts/dev/mods_ssot.py）。 */
export function modViewsDir(__dirname, modId) {
  const rel = path.join(modId, 'frontend', 'views')
  const candidates = [
    path.resolve(__dirname, '../mods', rel),
    path.resolve(__dirname, '../XCAGI/mods', rel),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return candidates[0]
}

export function createStaticCopyPlugin(__dirname) {
  return {
    name: 'copy-static',
    closeBundle() {
      const srcDir = path.resolve(__dirname, '../AI助手/static')
      const destDir = path.resolve(__dirname, 'public/static')
      if (fs.existsSync(srcDir)) {
        copyDir(srcDir, destDir)
        console.log('Static files copied successfully!')
      }
    },
  }
}
