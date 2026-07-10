import { createPackage } from '@electron/asar'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { afterEach, describe, expect, it } from 'vitest'

const verifier = path.join(__dirname, 'verify-packaged-runtime.cjs')
const tempRoots: string[] = []

function writeJson(filePath: string, value: unknown): void {
  mkdirSync(path.dirname(filePath), { recursive: true })
  writeFileSync(filePath, `${JSON.stringify(value)}\n`, 'utf8')
}

async function makeArchive(includeTransitiveDependency: boolean): Promise<string> {
  const root = mkdtempSync(path.join(tmpdir(), 'xcagi-packaged-runtime-'))
  tempRoots.push(root)
  const source = path.join(root, 'source')
  const archive = path.join(root, 'app.asar')

  writeJson(path.join(source, 'package.json'), {
    name: 'fixture-app',
    dependencies: { 'runtime-a': '1.0.0' }
  })
  const mainScript = path.join(source, 'dist', 'main.js')
  mkdirSync(path.dirname(mainScript), { recursive: true })
  writeFileSync(mainScript, 'module.exports = {}\n', 'utf8')
  writeJson(path.join(source, 'node_modules', 'runtime-a', 'package.json'), {
    name: 'runtime-a',
    version: '1.0.0',
    dependencies: { 'runtime-b': '1.0.0' }
  })
  if (includeTransitiveDependency) {
    writeJson(path.join(source, 'node_modules', 'runtime-b', 'package.json'), {
      name: 'runtime-b',
      version: '1.0.0'
    })
  }

  await createPackage(source, archive)
  return archive
}

afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true })
  }
})

describe('verify-packaged-runtime', () => {
  it('accepts a complete packaged dependency graph', async () => {
    const archive = await makeArchive(true)
    const result = spawnSync(process.execPath, [verifier, archive], { encoding: 'utf8' })

    expect(result.status).toBe(0)
    expect(result.stdout).toContain('verified 3 runtime packages')
  })

  it('rejects a missing transitive runtime dependency', async () => {
    const archive = await makeArchive(false)
    const result = spawnSync(process.execPath, [verifier, archive], { encoding: 'utf8' })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('runtime-a -> runtime-b')
  })
})
