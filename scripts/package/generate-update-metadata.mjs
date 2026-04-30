import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

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

let body = [
  `version: ${version}`,
  'files:',
  `  - url: ${name}`,
  `    sha512: ${sha512}`,
  `    size: ${size}`,
  `path: ${name}`,
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
