/**
 * 合并同 SKU 目录下 x64 / arm64 dmg，生成带双架构 files[] 的 latest-mac.yml（供 electron-updater）。
 * 用法: node scripts/package/merge-mac-update-manifest.mjs <sku-out-dir> <version>
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const [,, outDirArg, version] = process.argv
if (!outDirArg || !version) {
  console.error('Usage: node scripts/package/merge-mac-update-manifest.mjs <sku-out-dir> <version>')
  process.exit(2)
}

const outDir = path.resolve(outDirArg)
const arches = ['arm64', 'x64']
const files = []

for (const arch of arches) {
  const matches = fs
    .readdirSync(outDir)
    .filter((name) => name.endsWith('.dmg') && name.includes(`-mac-${arch}.dmg`))
  if (!matches.length) continue
  const name = matches.sort().at(-1)
  const artifact = path.join(outDir, name)
  const bytes = fs.readFileSync(artifact)
  files.push({
    url: name,
    sha512: crypto.createHash('sha512').update(bytes).digest('base64'),
    size: bytes.length,
    arch,
  })
}

if (!files.length) {
  console.error(`No mac dmg found in ${outDir}`)
  process.exit(1)
}

const primary = files.find((f) => f.arch === (process.arch === 'arm64' ? 'arm64' : 'x64')) || files[0]
const fileLines = files
  .map(
    (f) =>
      `  - url: ${f.url}\n    sha512: ${f.sha512}\n    size: ${f.size}\n    arch: ${f.arch}`,
  )
  .join('\n')

let body = [
  `version: ${version}`,
  'files:',
  fileLines,
  `path: ${primary.url}`,
  `sha512: ${primary.sha512}`,
  `releaseDate: '${new Date().toISOString()}'`,
  `stagingPercentage: ${process.env.XCAGI_STAGING_PERCENTAGE || '100'}`,
  `forceUpgrade: ${process.env.XCAGI_FORCE_UPGRADE || 'false'}`,
  `minVersion: ${process.env.XCAGI_MIN_VERSION || version}`,
].join('\n')

const privateKey = process.env.XCAGI_UPDATE_ED25519_PRIVATE_KEY
if (privateKey) {
  const key = crypto.createPrivateKey(privateKey.replace(/\\n/g, '\n'))
  const signature = crypto.sign(null, Buffer.from(body, 'utf8'), key).toString('base64')
  body += `\nsignature: ed25519:${signature}`
}

const output = path.join(outDir, 'latest-mac.yml')
fs.writeFileSync(output, `${body}\n`, 'utf8')
console.log(`Generated ${output} (${files.map((f) => f.arch).join(', ')})`)
