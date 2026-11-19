import { createPublicKey, verify } from 'node:crypto'
import type { CustomPublishOptions } from 'builder-util-runtime'
import type { AppUpdater } from 'electron-updater'
import { GenericProvider } from 'electron-updater/out/providers/GenericProvider'
import type { ProviderRuntimeOptions } from 'electron-updater/out/providers/Provider'

export class SignedUpdateProvider extends GenericProvider {
  private readonly publicKey: string

  constructor(
    { url, channel, publicKey }: CustomPublishOptions,
    updater: AppUpdater,
    runtimeOptions: ProviderRuntimeOptions,
  ) {
    if (typeof url !== 'string' || typeof publicKey !== 'string') {
      throw new Error('缺少桌面更新源或清单验签公钥')
    }
    super({ url, channel, provider: 'generic' }, updater, runtimeOptions)
    this.publicKey = publicKey
  }

  protected override async httpRequest(
    ...args: Parameters<GenericProvider['httpRequest']>
  ): Promise<string> {
    const text = (await super.httpRequest(...args))?.replace(/\r\n/g, '\n').trimEnd() || ''
    const match = /\nsignature: ed25519:([A-Za-z0-9+/]+={0,2})$/.exec(text)
    if (!match) {
      throw new Error('更新元数据缺少 Ed25519 二次签名')
    }
    const body = text.slice(0, match.index).trimEnd()
    const publicKey = createPublicKey(this.publicKey.replace(/\\n/g, '\n'))
    if (publicKey.asymmetricKeyType !== 'ed25519'
        || !verify(null, Buffer.from(body), publicKey, Buffer.from(match[1], 'base64'))) {
      throw new Error('更新元数据 Ed25519 二次签名校验失败')
    }
    return body
  }

  override async getLatestVersion() {
    const info = await super.getLatestVersion()
    // The upstream downloader uses these same descriptors for cache checks and download integrity.
    if (this.resolveFiles(info).some(({ info: file }) => !/^[A-Za-z0-9+/]{86}==$/.test(file.sha512))) {
      throw new Error('更新制品缺少有效的 SHA-512 校验值')
    }
    return info
  }
}
