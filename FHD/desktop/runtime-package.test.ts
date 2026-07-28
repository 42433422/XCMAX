import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

// The packaging hook is CommonJS because electron-builder loads it directly.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { writeDesktopRuntimePackage } = require('./build/before-pack.cjs') as {
  writeDesktopRuntimePackage: (desktopDir: string) => string
}
// eslint-disable-next-line @typescript-eslint/no-require-imports
const asar = require('@electron/asar') as {
  createPackage: (source: string, destination: string) => Promise<void>
  extractFile: (archive: string, filename: string) => Buffer
}

const temporaryDirectories: string[] = []

function createDesktopFixture() {
  const desktopDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-runtime-package-'))
  temporaryDirectories.push(desktopDir)
  fs.mkdirSync(path.join(desktopDir, 'dist'))
  fs.writeFileSync(
    path.join(desktopDir, 'package.json'),
    JSON.stringify({
      name: 'xcagi-desktop',
      version: '1.2.3',
      private: true,
      author: 'XCAGI',
      description: 'desktop shell',
      main: 'dist/main.js',
      type: 'commonjs',
      scripts: { build: 'should-not-be-packaged' },
      devDependencies: { electron: 'test-only' },
    }),
  )
  fs.writeFileSync(path.join(desktopDir, 'dist', 'main.js'), "'use strict'\n")
  return desktopDir
}

afterEach(() => {
  while (temporaryDirectories.length) {
    fs.rmSync(temporaryDirectories.pop()!, { recursive: true, force: true })
  }
})

describe('desktop ASAR runtime package', () => {
  it('writes a dist-local manifest whose main resolves to the built entry', () => {
    const desktopDir = createDesktopFixture()

    const outputPath = writeDesktopRuntimePackage(desktopDir)
    const runtimePackage = JSON.parse(fs.readFileSync(outputPath, 'utf8'))

    expect(outputPath).toBe(path.join(desktopDir, 'dist', 'package.json'))
    expect(runtimePackage).toEqual({
      name: 'xcagi-desktop',
      version: '1.2.3',
      private: true,
      author: 'XCAGI',
      description: 'desktop shell',
      main: 'main.js',
      type: 'commonjs',
    })
    expect(fs.existsSync(path.join(path.dirname(outputPath), runtimePackage.main))).toBe(true)
    expect(runtimePackage).not.toHaveProperty('scripts')
    expect(runtimePackage).not.toHaveProperty('devDependencies')
  })

  it('keeps the dist-local manifest when the desktop files are archived', async () => {
    const desktopDir = createDesktopFixture()
    const outputPath = writeDesktopRuntimePackage(desktopDir)
    const archivePath = path.join(desktopDir, 'app.asar')

    await asar.createPackage(desktopDir, archivePath)

    const archivedManifest = JSON.parse(
      asar.extractFile(archivePath, 'dist/package.json').toString('utf8'),
    )
    expect(archivedManifest.main).toBe('main.js')
    expect(asar.extractFile(archivePath, `dist/${archivedManifest.main}`).length).toBeGreaterThan(0)
    expect(outputPath).toBe(path.join(desktopDir, 'dist', 'package.json'))
  })

  it('fails closed before packaging when the compiled desktop entry is absent', () => {
    const desktopDir = createDesktopFixture()
    fs.rmSync(path.join(desktopDir, 'dist', 'main.js'))

    expect(() => writeDesktopRuntimePackage(desktopDir)).toThrow('desktop runtime entry is missing')
    expect(fs.existsSync(path.join(desktopDir, 'dist', 'package.json'))).toBe(false)
  })
})
