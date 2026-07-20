import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import asar from '@electron/asar'

const afterPack = require('./build/after-pack.cjs') as {
  REQUIRED_RUNTIME_PACKAGES: string[]
  verifyPackagedRuntimeDependencies: (asarPath: string) => void
}

const temporaryRoots: string[] = []

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

async function createRuntimeAsar(missingPackage?: string): Promise<string> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-after-pack-test-'))
  temporaryRoots.push(root)
  const source = path.join(root, 'source')
  for (const packageName of afterPack.REQUIRED_RUNTIME_PACKAGES) {
    if (packageName === missingPackage) continue
    const packageDir = path.join(source, 'node_modules', packageName)
    fs.mkdirSync(packageDir, { recursive: true })
    fs.writeFileSync(
      path.join(packageDir, 'package.json'),
      JSON.stringify({ name: packageName, version: '1.0.0' }),
    )
  }
  const archive = path.join(root, 'app.asar')
  await asar.createPackage(source, archive)
  return archive
}

describe('afterPack runtime dependency gate', () => {
  it('accepts an archive containing every updater runtime dependency', async () => {
    const archive = await createRuntimeAsar()
    expect(() => afterPack.verifyPackagedRuntimeDependencies(archive)).not.toThrow()
  })

  it('fails before signing when a runtime dependency is missing', async () => {
    const archive = await createRuntimeAsar('builder-util-runtime')
    expect(() => afterPack.verifyPackagedRuntimeDependencies(archive)).toThrow(
      'builder-util-runtime',
    )
  })
})
