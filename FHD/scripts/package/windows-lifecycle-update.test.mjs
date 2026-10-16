import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawnSync, spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const script = fileURLToPath(new URL('./windows-lifecycle-update.mjs', import.meta.url))
test('private feed binds bytes and build identity, requires release signing, and serves ranges only on loopback', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-feed-'))
  const file = path.join(dir, 'candidate.exe'), bytes = Buffer.from('isolated installer fixture'), sha = 'a'.repeat(40)
  fs.writeFileSync(file, bytes)
  fs.writeFileSync(path.join(dir, 'delivery-receipt.json'), JSON.stringify({ git_sha: sha, version: '1.0.0.6', sha256: crypto.createHash('sha256').update(bytes).digest('hex') }))
  const { privateKey, publicKey } = crypto.generateKeyPairSync('ed25519')
  const env = { ...process.env, CANDIDATE_SHA: sha, XCAGI_UPDATE_ED25519_PRIVATE_KEY: privateKey.export({ type: 'pkcs8', format: 'pem' }) }
  const prepare = e => spawnSync(process.execPath, [script, 'prepare', dir, file], { env: e, encoding: 'utf8' })
  let child
  try {
    assert.notEqual(prepare({ ...env, CANDIDATE_SHA: 'b'.repeat(40) }).status, 0)
    assert.notEqual(prepare({ ...env, XCAGI_UPDATE_ED25519_PRIVATE_KEY: '' }).status, 0)
    assert.equal(prepare(env).status, 0)
    const text = fs.readFileSync(path.join(dir, 'latest.yml'), 'utf8'), lines = text.trimEnd().split('\n'), sig = lines.pop().slice('signature: ed25519:'.length)
    assert.ok(crypto.verify(null, Buffer.from(lines.join('\n')), publicKey, Buffer.from(sig, 'base64')))
    assert.ok(!crypto.verify(null, Buffer.from(lines.join('\n') + 'tamper'), publicKey, Buffer.from(sig, 'base64')))
    assert.match(text, /version: 1\.0\.0\nproductVersion: 1\.0\.0\.6/)
    child = spawn(process.execPath, [script, 'serve', dir, file], { stdio: 'pipe' })
    let response
    for (let i = 0; i < 50; i++) {
      try { response = await fetch('http://127.0.0.1:18765/latest.yml'); break } catch { await new Promise(r => setTimeout(r, 50)) }
    }
    assert.equal(await response.text(), text)
    response = await fetch('http://127.0.0.1:18765/candidate.exe', { headers: { Range: 'bytes=1-4' } })
    assert.equal(response.status, 206); assert.equal(await response.text(), bytes.subarray(1, 5).toString())
    assert.equal((await fetch('http://127.0.0.1:18765/delivery-receipt.json')).status, 404)
    fs.appendFileSync(file, 'tamper'); assert.notEqual(prepare(env).status, 0)
  } finally { child?.kill(); fs.rmSync(dir, { recursive: true, force: true }) }
})
