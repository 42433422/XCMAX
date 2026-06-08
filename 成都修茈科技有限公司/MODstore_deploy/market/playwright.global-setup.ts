import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

function lockDigest(rel: string): string {
  const p = join(__dirname, rel)
  if (!existsSync(p)) return `${rel}=absent`
  const buf = readFileSync(p)
  const h = createHash('sha256').update(buf).digest('hex').slice(0, 12)
  return `${rel} sha256[:12]=${h}`
}

export default async function globalSetup(): Promise<void> {
  console.log(
    [
      '[playwright-env] reproducibility fingerprint',
      `node=${process.version}`,
      `PLAYWRIGHT_BASE_URL=${process.env.PLAYWRIGHT_BASE_URL || '(default)'}`,
      `PLAYWRIGHT_PORT=${process.env.PLAYWRIGHT_PORT || '(default)'}`,
      lockDigest('package-lock.json'),
    ].join('\n'),
  )
}
