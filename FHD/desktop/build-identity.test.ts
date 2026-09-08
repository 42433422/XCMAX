import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { readDesktopBuildIdentity } from './build-identity'

describe('independent packaged build identities', () => {
  let root: string
  beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-build-identity-')); fs.mkdirSync(path.join(root, 'backend')) })
  afterEach(() => fs.rmSync(root, { recursive: true, force: true }))
  const hostSha = 'a'.repeat(40)
  const backendSha = 'b'.repeat(40)

  it('reports matching real metadata without trusting a development override', () => {
    fs.writeFileSync(path.join(root, 'build-info.json'), JSON.stringify({ gitSha: hostSha, productVersion: '1.2' }))
    fs.writeFileSync(path.join(root, 'backend/build-info.json'), JSON.stringify({ buildSha: hostSha, version: '1.2' }))
    expect(readDesktopBuildIdentity(root, true, backendSha)).toMatchObject({ desktop: { status: 'known', gitSha: hostSha, productVersion: '1.2' }, bundledBackend: { gitSha: hostSha }, shaConsistent: true, versionConsistent: true })
  })
  it('retains mismatched identities instead of merging them', () => {
    fs.writeFileSync(path.join(root, 'build-info.json'), JSON.stringify({ gitSha: hostSha }))
    fs.writeFileSync(path.join(root, 'backend/build-info.json'), JSON.stringify({ gitSha: backendSha }))
    expect(readDesktopBuildIdentity(root, true)).toMatchObject({ desktop: { gitSha: hostSha }, bundledBackend: { gitSha: backendSha }, shaConsistent: false })
  })
  it('reports a version mismatch independently of a matching SHA', () => {
    fs.writeFileSync(path.join(root, 'build-info.json'), JSON.stringify({ gitSha: hostSha, productVersion: '1.2' }))
    fs.writeFileSync(path.join(root, 'backend/build-info.json'), JSON.stringify({ gitSha: hostSha, productVersion: '1.3' }))
    expect(readDesktopBuildIdentity(root, true)).toMatchObject({ shaConsistent: true, versionConsistent: false })
  })
  it('rejects conflicting SHA aliases in the same component', () => {
    fs.writeFileSync(path.join(root, 'build-info.json'), JSON.stringify({ gitSha: hostSha, buildSha: backendSha }))
    expect(readDesktopBuildIdentity(root, true)).toMatchObject({ desktop: { status: 'invalid', gitSha: null }, shaConsistent: null })
  })
  it('never substitutes the backend SHA when desktop metadata is missing', () => {
    fs.writeFileSync(path.join(root, 'backend/build-info.json'), JSON.stringify({ gitSha: backendSha }))
    expect(readDesktopBuildIdentity(root, true)).toMatchObject({ desktop: { status: 'missing', gitSha: null }, bundledBackend: { gitSha: backendSha }, shaConsistent: null })
  })
  it.each([{ label: 'broken JSON', raw: '{broken' }, { label: 'array', raw: '[]' }, { label: 'unknown SHA', raw: '{"gitSha":"unknown"}' }, { label: 'oversized', raw: 'x'.repeat(65537) }])('marks $label metadata invalid', ({ raw }) => {
    fs.writeFileSync(path.join(root, 'build-info.json'), raw)
    expect(readDesktopBuildIdentity(root, true)).toMatchObject({ desktop: { status: 'invalid', gitSha: null }, shaConsistent: null })
  })
  it('labels development identities explicitly', () => {
    expect(readDesktopBuildIdentity(root, false, hostSha)).toMatchObject({ desktop: { status: 'development', gitSha: hostSha }, bundledBackend: null, shaConsistent: null })
  })
})
