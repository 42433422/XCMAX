/** Build-time version injection from the repository VERSION.md SSOT. */
const fs = require('node:fs')
const path = require('node:path')

const desktopDir = __dirname
const repoRoot = path.resolve(desktopDir, '..', '..', '..')
const versionFile = path.join(repoRoot, 'FHD', 'VERSION.md')
const pkgFile = path.join(desktopDir, '..', 'package.json')
const buildInfoFile = path.join(desktopDir, '..', 'resources', 'build-info.json')

function log(msg) {
  console.log(`[inject-version] ${msg}`)
}

try {
  if (!fs.existsSync(versionFile)) {
    throw new Error(`VERSION SSOT 不存在: ${versionFile}`)
  }

  const versionText = fs.readFileSync(versionFile, 'utf8')
  const productMatch = versionText.match(/\*\*XCAGI 稳定产品版本\*\*\s*\|\s*`([\d.]+)`/)
  const toolchainMatch = versionText.match(/\*\*工具链兼容版本\*\*\s*\|\s*`([\d.]+)`/)
  if (!productMatch || !toolchainMatch) throw new Error('无法从 VERSION.md 解析产品/工具链版本')
  const productVersion = productMatch[1]
  const toolchainVersion = toolchainMatch[1]

  const pkgRaw = fs.readFileSync(pkgFile, 'utf8')
  const pkg = JSON.parse(pkgRaw)
  if (pkg.version !== toolchainVersion) {
    pkg.version = toolchainVersion
    fs.writeFileSync(pkgFile, JSON.stringify(pkg, null, 2) + '\n', 'utf8')
  }

  const buildInfo = JSON.parse(fs.readFileSync(buildInfoFile, 'utf8'))
  if (buildInfo.version !== productVersion) {
    buildInfo.version = productVersion
    fs.writeFileSync(buildInfoFile, JSON.stringify(buildInfo) + '\n', 'utf8')
  }
  log(`版本已对齐: product=${productVersion}, toolchain=${toolchainVersion}`)
} catch (error) {
  log(`注入失败: ${error.message}`)
  process.exit(1)
}
