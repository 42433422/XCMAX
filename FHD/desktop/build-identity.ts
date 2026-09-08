/** Declared package identities, kept separate from running backend verification. */
import fs from 'node:fs'
import path from 'node:path'

type BuildIdentity = {
  source: string
  status: 'known' | 'missing' | 'invalid' | 'development'
  gitSha: string | null
  productVersion: string | null
}

function sha(value: unknown): string | null {
  return typeof value === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(value.trim()) ? value.trim().toLowerCase() : null
}

function read(resources: string, relative: string): BuildIdentity {
  const result: BuildIdentity = { source: relative, status: 'missing', gitSha: null, productVersion: null }
  const filename = path.join(resources, relative)
  try {
    if (!fs.existsSync(filename)) return result
    if (fs.statSync(filename).size > 65536) return { ...result, status: 'invalid' }
    const data: unknown = JSON.parse(fs.readFileSync(filename, 'utf8'))
    if (!data || typeof data !== 'object' || Array.isArray(data)) return { ...result, status: 'invalid' }
    const row = data as Record<string, unknown>
    const gitSha = sha(row.gitSha ?? row.buildSha)
    if (row.gitSha !== undefined && row.buildSha !== undefined && sha(row.gitSha) !== sha(row.buildSha)) {
      return { ...result, status: 'invalid' }
    }
    const version = row.productVersion ?? row.version
    return { ...result, status: gitSha ? 'known' : 'invalid', gitSha, productVersion: typeof version === 'string' ? version : null }
  } catch {
    return { ...result, status: 'invalid' }
  }
}

export function readDesktopBuildIdentity(resources: string, packaged: boolean, developmentSha?: string) {
  if (!packaged) return {
    desktop: { source: 'development_environment', status: 'development', gitSha: sha(developmentSha), productVersion: null },
    bundledBackend: null,
    shaConsistent: null,
    versionConsistent: null,
  }
  const desktop = read(resources, 'build-info.json')
  const bundledBackend = read(resources, 'backend/build-info.json')
  return {
    desktop, bundledBackend,
    shaConsistent: desktop.gitSha && bundledBackend.gitSha ? desktop.gitSha === bundledBackend.gitSha : null,
    versionConsistent: desktop.productVersion && bundledBackend.productVersion ? desktop.productVersion === bundledBackend.productVersion : null,
  }
}
