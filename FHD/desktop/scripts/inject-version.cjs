/**
 * electron-builder 构建前注入版本号。
 *
 * 从 FHD/release/VERSION 读取产品版本（如 1.0.0.1），写入 package.json 的 version 字段。
 * 这样版本号只需在 FHD/release/VERSION 维护一处，发布时无需手动同步 package.json。
 */
const fs = require('node:fs')
const path = require('node:path')

const desktopDir = __dirname
const repoRoot = path.resolve(desktopDir, '..', '..', '..')
const versionFile = path.join(repoRoot, 'FHD', 'release', 'VERSION')
const pkgFile = path.join(desktopDir, '..', 'package.json')

function log(msg) {
  console.log(`[inject-version] ${msg}`)
}

try {
  if (!fs.existsSync(versionFile)) {
    log(`VERSION 文件不存在: ${versionFile}，跳过注入`)
    process.exit(0)
  }

  const version = fs.readFileSync(versionFile, 'utf8').trim()
  if (!version) {
    log('VERSION 文件为空，跳过注入')
    process.exit(0)
  }

  const pkgRaw = fs.readFileSync(pkgFile, 'utf8')
  const pkg = JSON.parse(pkgRaw)

  if (pkg.version === version) {
    log(`版本一致 (${version})，无需更新`)
    process.exit(0)
  }

  pkg.version = version
  fs.writeFileSync(pkgFile, JSON.stringify(pkg, null, 2) + '\n', 'utf8')
  log(`版本已注入: ${version}`)
} catch (error) {
  log(`注入失败: ${error.message}`)
  process.exit(1)
}