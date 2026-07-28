import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

// The verifier is CommonJS because package release scripts invoke it directly.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { verifyRuntimeAsarDependencyClosure } = require('./build/verify-runtime-asar.cjs') as {
  verifyRuntimeAsarDependencyClosure: (archivePath: string) => {
    archivePath: string
    packageCount: number
    packageNames: string[]
  }
}
// eslint-disable-next-line @typescript-eslint/no-require-imports
const asar = require('@electron/asar') as {
  createPackage: (source: string, destination: string) => Promise<void>
}

const temporaryDirectories: string[] = []

function writePackage(root: string, relativeDirectory: string, manifest: Record<string, unknown>) {
  const directory = path.join(root, relativeDirectory)
  fs.mkdirSync(directory, { recursive: true })
  fs.writeFileSync(path.join(directory, 'package.json'), `${JSON.stringify(manifest, null, 2)}\n`)
  fs.writeFileSync(path.join(directory, 'index.js'), "'use strict'\n")
}

async function createArchive(includeGracefulFs: boolean) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-runtime-closure-'))
  temporaryDirectories.push(root)
  writePackage(root, '.', {
    name: 'xcagi-desktop',
    version: '1.0.0',
    dependencies: { 'electron-updater': 'test' },
  })
  writePackage(root, 'node_modules/electron-updater', {
    name: 'electron-updater',
    version: 'test',
    dependencies: { 'fs-extra': 'test' },
  })
  writePackage(root, 'node_modules/fs-extra', {
    name: 'fs-extra',
    version: 'test',
    dependencies: { 'graceful-fs': 'test' },
  })
  if (includeGracefulFs) {
    writePackage(root, 'node_modules/graceful-fs', {
      name: 'graceful-fs',
      version: 'test',
    })
  }
  const archivePath = path.join(root, 'app.asar')
  await asar.createPackage(root, archivePath)
  return archivePath
}

afterEach(() => {
  while (temporaryDirectories.length) {
    fs.rmSync(temporaryDirectories.pop()!, { recursive: true, force: true })
  }
})

describe('packaged runtime dependency closure', () => {
  it('accepts a flattened electron-updater dependency closure in the ASAR', async () => {
    const archivePath = await createArchive(true)

    const result = verifyRuntimeAsarDependencyClosure(archivePath)

    expect(result.packageCount).toBe(4)
    expect(result.packageNames).toEqual(
      expect.arrayContaining(['xcagi-desktop', 'electron-updater', 'fs-extra', 'graceful-fs']),
    )
  })

  it('fails closed when the packaged updater closure omits graceful-fs', async () => {
    const archivePath = await createArchive(false)

    expect(() => verifyRuntimeAsarDependencyClosure(archivePath)).toThrow(
      'runtime dependency is missing: fs-extra requires graceful-fs',
    )
  })
})
