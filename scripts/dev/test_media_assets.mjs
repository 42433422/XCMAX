import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { materializeMediaAssets, verifyMediaAssets } from './materialize_media_assets.mjs'

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'media-assets-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const source = 'FHD/frontend/public/staff.png'
  const target = 'FHD/frontend/public/staff-busy.png'
  const bytes = Buffer.from('original media bytes')
  fs.mkdirSync(path.dirname(path.join(root, source)), { recursive: true })
  fs.writeFileSync(path.join(root, source), bytes)
  fs.mkdirSync(path.join(root, 'config'))
  const entry = { scope: 'frontend', source, sha256: createHash('sha256').update(bytes).digest('hex'), size: bytes.length }
  const data = { schema: 'xcmax.media-aliases/v1', aliases: { [target]: entry } }
  const save = () => fs.writeFileSync(path.join(root, 'config/media-aliases.json'), JSON.stringify(data))
  save()
  return { root, source, target, bytes, entry, data, save }
}

test('the real product registry pins every canonical asset', () => {
  assert.equal(verifyMediaAssets().length, 19)
})

test('a clean checkout restores exact legacy URLs as normal files and is idempotent', (t) => {
  const f = fixture(t)
  assert.equal(verifyMediaAssets('frontend', f.root).length, 1)
  assert.equal(fs.existsSync(path.join(f.root, f.target)), false)
  assert.equal(materializeMediaAssets('frontend', f.root), 1)
  assert.deepEqual(fs.readFileSync(path.join(f.root, f.target)), f.bytes)
  assert.equal(fs.lstatSync(path.join(f.root, f.target)).isSymbolicLink(), false)
  assert.equal(materializeMediaAssets('market', f.root), 0)
  fs.writeFileSync(path.join(f.root, f.target), 'outdated generated file')
  materializeMediaAssets('frontend', f.root)
  assert.deepEqual(fs.readFileSync(path.join(f.root, f.target)), f.bytes)
})

test('corrupt canonical input fails before any output is created', (t) => {
  const f = fixture(t)
  fs.writeFileSync(path.join(f.root, f.source), 'corrupt input')
  assert.throws(() => materializeMediaAssets('frontend', f.root), /checksum mismatch/)
  assert.equal(fs.existsSync(path.join(f.root, f.target)), false)
})

test('unregistered paths, traversals, and alias chains fail closed', (t) => {
  const f = fixture(t)
  for (const source of ['private/data.png', 'FHD/frontend/public/../private.png', f.target]) {
    f.entry.source = source
    f.save()
    assert.throws(() => materializeMediaAssets('frontend', f.root), /Unregistered|Unsafe/)
  }
  assert.throws(() => materializeMediaAssets('unknown', f.root), /Unknown media scope/)
})

test('a malicious existing alias cannot overwrite an unrelated file through a symlink', (t) => {
  const f = fixture(t)
  const other = path.join(f.root, 'untouched.txt')
  fs.writeFileSync(other, 'leave intact')
  fs.symlinkSync(other, path.join(f.root, f.target))
  assert.throws(() => materializeMediaAssets('frontend', f.root), /symlink/)
  assert.equal(fs.readFileSync(other, 'utf8'), 'leave intact')
  fs.unlinkSync(path.join(f.root, f.target))
  fs.symlinkSync(path.join(f.root, 'does-not-exist'), path.join(f.root, f.target))
  assert.throws(() => materializeMediaAssets('frontend', f.root), /symlink/)
})
