import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const [,, artifactPath, version, platform = 'win'] = process.argv
if (!artifactPath || !version) {
  console.error('Usage: node scripts/package/generate-update-metadata.mjs <artifact> <version> [win|mac]')
  process.exit(2)
}

const artifact = path.resolve(artifactPath)
const bytes = fs.readFileSync(artifact)
const sha512 = crypto.createHash('sha512').update(bytes).digest('base64')
const size = bytes.length
const name = path.basename(artifact)
const isMac = platform === 'mac' || name.endsWith('.dmg')
const output = isMac ? 'latest-mac.yml' : 'latest.yml'

if (isMac && path.extname(name).toLowerCase() !== '.zip') {
  console.error(`macOS update metadata requires a ZIP artifact, got: ${name}`)
  process.exit(2)
}

function resolveBuildSha() {
  const fromEnv = String(process.env.XCAGI_BUILD_SHA || process.env.GITHUB_SHA || '').trim()
  if (fromEnv) return fromEnv
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

const buildSha = resolveBuildSha()
if (!/^[0-9a-fA-F]{40}$/.test(buildSha)) {
  console.error(`update metadata requires a full Git SHA buildSha, got: ${JSON.stringify(buildSha)}`)
  process.exit(2)
}
const productVersion = String(process.env.XCAGI_PRODUCT_VERSION || version).trim()
if (!/^\d+\.\d+\.\d+(?:\.\d+)?$/.test(productVersion)) {
  console.error(`invalid product version: ${JSON.stringify(productVersion)}`)
  process.exit(2)
}
const releaseId = String(
  process.env.XCAGI_RELEASE_ID || `xcagi-${productVersion}-${buildSha.toLowerCase()}`,
).trim()
const expectedReleaseId = `xcagi-${productVersion}-${buildSha.toLowerCase()}`
if (releaseId !== expectedReleaseId) {
  console.error(`invalid immutable release id: ${JSON.stringify(releaseId)}`)
  process.exit(2)
}
const artifactUrlPrefix = String(process.env.XCAGI_ARTIFACT_URL_PREFIX || '').trim().replace(/\/+$/, '')
if (artifactUrlPrefix && !/^https:\/\/[^/?#]+(?:\/[^?#]*)?$/.test(artifactUrlPrefix)) {
  console.error(`XCAGI_ARTIFACT_URL_PREFIX must be an absolute HTTPS path: ${JSON.stringify(artifactUrlPrefix)}`)
  process.exit(2)
}
const artifactUrl = artifactUrlPrefix ? `${artifactUrlPrefix}/${encodeURIComponent(name)}` : name
const releaseNotes = String(process.env.XCAGI_RELEASE_NOTES || '').trim()

/**
 * B8 修复：为最终安装包生成内容定义分块 blockmap（electron-builder differential 更新用）。
 *
 * 流水线对 NSIS exe 做二次包装（UI 重打包 + 重命名），electron-builder 原生
 * blockmap 对应的是原始 exe，哈希已失配——因此必须在最终产物上重新生成。
 * 复用 app-builder-lib 内置 buildBlockMap（与 NsisTarget 相同参数：gzip、<file>.blockmap），
 * 保证与 electron-updater 的 differentialDownloader 完全兼容。
 * 生成失败仅告警并降级为全量下载（latest.yml 不引用 blockmap），不阻断发布。
 */
async function buildBlockMapForArtifact() {
  const selfDir = path.dirname(fileURLToPath(import.meta.url))
  const blockmapModule = path.resolve(
    selfDir,
    '..',
    '..',
    'desktop',
    'node_modules',
    'app-builder-lib',
    'out',
    'targets',
    'blockmap',
    'blockmap.js',
  )
  if (!fs.existsSync(blockmapModule)) {
    console.warn('blockmap generation skipped: app-builder-lib not found (full download fallback)')
    return null
  }
  const { createRequire } = await import('node:module')
  const require = createRequire(import.meta.url)
  const { buildBlockMap } = require(blockmapModule)
  const blockMapFile = `${artifact}.blockmap`
  await buildBlockMap(artifact, 'gzip', blockMapFile)
  return blockMapFile
}

let blockmapEntryLines = []
try {
  const blockMapFile = await buildBlockMapForArtifact()
  if (blockMapFile) {
    const bmBytes = fs.readFileSync(blockMapFile)
    const bmSha512 = crypto.createHash('sha512').update(bmBytes).digest('base64')
    const bmName = path.basename(blockMapFile)
    const bmUrl = artifactUrlPrefix ? `${artifactUrlPrefix}/${encodeURIComponent(bmName)}` : bmName
    blockmapEntryLines = [`  - url: ${bmUrl}`, `    sha512: ${bmSha512}`, `    size: ${bmBytes.length}`]
    console.log(`Generated ${bmName} (${bmBytes.length} bytes)`)
  }
} catch (error) {
  console.warn(`blockmap generation failed (full download fallback): ${error && error.message ? error.message : error}`)
}

function yamlEscapeBlock(text) {
  return text
    .split(/\r?\n/)
    .map((line) => `  ${line}`)
    .join('\n')
}

function yamlEscapeScalar(value) {
  const text = String(value || '')
  if (/[:#{}[\],&*?|>!%@`]/.test(text) || /^\s|\s$/.test(text) || text === '') {
    return JSON.stringify(text)
  }
  return text
}

/** 支持 XCAGI_RELEASE_MEDIA_JSON 数组，或单条 POSTER/VIDEO/CAPTION 环境变量。 */
function resolveReleaseMediaLines() {
  const slides = []
  const jsonRaw = String(process.env.XCAGI_RELEASE_MEDIA_JSON || '').trim()
  if (jsonRaw) {
    let parsed
    try {
      parsed = JSON.parse(jsonRaw)
    } catch (error) {
      console.error('XCAGI_RELEASE_MEDIA_JSON 不是合法 JSON:', error.message || error)
      process.exit(2)
    }
    const list = Array.isArray(parsed) ? parsed : [parsed]
    for (const item of list) {
      if (!item || typeof item !== 'object') continue
      const posterUrl = String(item.posterUrl || item.poster || '').trim()
      if (!posterUrl) continue
      slides.push({
        posterUrl,
        videoUrl: String(item.videoUrl || item.video || '').trim(),
        caption: String(item.caption || item.title || '').trim(),
      })
    }
  } else {
    const posterUrl = String(process.env.XCAGI_RELEASE_POSTER_URL || '').trim()
    if (posterUrl) {
      slides.push({
        posterUrl,
        videoUrl: String(process.env.XCAGI_RELEASE_VIDEO_URL || '').trim(),
        caption: String(process.env.XCAGI_RELEASE_MEDIA_CAPTION || '').trim(),
      })
    }
  }
  if (!slides.length) return []
  const lines = ['releaseMedia:']
  for (const slide of slides.slice(0, 8)) {
    lines.push(`  - posterUrl: ${yamlEscapeScalar(slide.posterUrl)}`)
    if (slide.videoUrl) lines.push(`    videoUrl: ${yamlEscapeScalar(slide.videoUrl)}`)
    if (slide.caption) lines.push(`    caption: ${yamlEscapeScalar(slide.caption)}`)
  }
  return lines
}

const releaseMediaLines = resolveReleaseMediaLines()

let body = [
  `version: ${version}`,
  ...(productVersion !== version ? [`productVersion: ${productVersion}`] : []),
  ...(buildSha ? [`buildSha: ${buildSha}`] : []),
  `releaseId: ${releaseId}`,
  ...(releaseNotes
    ? [`releaseNotes: |`, yamlEscapeBlock(releaseNotes)]
    : [
        'releaseNotes: |',
        `  版本 ${productVersion || version}`,
        ...(buildSha ? [`  构建 ${buildSha.slice(0, 12)}`] : []),
        '  ',
        '  • 更新桌面壳与本地后端运行时',
        '  • 保留本机业务数据与已安装 Mod',
        '  • 安装完成后重新加载进入新版本',
      ]),
  ...releaseMediaLines,
  'files:',
  `  - url: ${artifactUrl}`,
  `    sha512: ${sha512}`,
  `    size: ${size}`,
  ...blockmapEntryLines,
  `path: ${artifactUrl}`,
  `sha512: ${sha512}`,
  `releaseDate: '${new Date().toISOString()}'`,
  `stagingPercentage: ${process.env.XCAGI_STAGING_PERCENTAGE || '100'}`,
  `forceUpgrade: ${process.env.XCAGI_FORCE_UPGRADE || 'false'}`,
  `minVersion: ${process.env.XCAGI_MIN_VERSION || version}`
].join('\n')

const privateKey = process.env.XCAGI_UPDATE_ED25519_PRIVATE_KEY
if (privateKey) {
  const key = crypto.createPrivateKey(privateKey.replace(/\\n/g, '\n'))
  const signature = crypto.sign(null, Buffer.from(body, 'utf8'), key).toString('base64')
  body += `\nsignature: ed25519:${signature}`
}

fs.writeFileSync(path.join(path.dirname(artifact), output), `${body}\n`, 'utf8')
console.log(`Generated ${output}`)
