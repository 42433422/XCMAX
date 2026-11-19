import { createHash, generateKeyPairSync, sign } from 'node:crypto'
import { describe, expect, it, vi } from 'vitest'
import type { AppUpdater } from 'electron-updater'
import type { ProviderRuntimeOptions } from 'electron-updater/out/providers/Provider'
import { SignedUpdateProvider } from './signed-update-provider.js'

const { privateKey, publicKey } = generateKeyPairSync('ed25519')
const checksum = createHash('sha512').update('update package').digest('base64')
const manifest = `version: 1.0.7
files:
  - url: update-arm64.zip
    sha512: ${checksum}
buildSha: build-7
stagingPercentage: 25`

function signed(body: string) {
  return `${body}\nsignature: ed25519:${sign(null, Buffer.from(body), privateKey).toString('base64')}\n`
}

function provider(text: string) {
  const request = vi.fn().mockResolvedValue(text)
  const updater = { isAddNoCacheQuery: false } as unknown as AppUpdater
  const runtime = { executor: { request }, platform: 'darwin' } as unknown as ProviderRuntimeOptions
  const feed = {
    provider: 'custom' as const,
    url: 'https://updates.example.com/testing/',
    channel: 'beta',
    publicKey: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
  }
  return { updater: new SignedUpdateProvider(feed, updater, runtime), request }
}

describe('signed electron-updater provider', () => {
  it('resolves the artifact from the single verified channel response', async () => {
    const { updater, request } = provider(signed(manifest).replace(/\n/g, '\r\n'))
    const info = await updater.getLatestVersion()
    expect(info).toMatchObject({ version: '1.0.7', buildSha: 'build-7', stagingPercentage: 25 })
    expect(updater.resolveFiles(info)[0]).toMatchObject({ info: { sha512: checksum } })
    expect(updater.resolveFiles(info)[0].url.href).toBe('https://updates.example.com/testing/update-arm64.zip')
    expect(request).toHaveBeenCalledWith(expect.objectContaining({ path: '/testing/beta-mac.yml' }), undefined)
    expect(request).toHaveBeenCalledOnce()
  })

  it.each([
    [manifest, /缺少 Ed25519/],
    [signed(manifest).replace('update-arm64.zip', 'different.zip'), /Ed25519 二次签名校验失败/],
    [signed(manifest) + 'stagingPercentage: 100\n', /缺少 Ed25519/],
    [signed(manifest.replace(checksum, 'invalid-digest')), /SHA-512/],
  ])('rejects invalid channel responses before returning any artifact', async (text, expected) => {
    await expect(provider(text).updater.getLatestVersion()).rejects.toThrow(expected)
  })
})
