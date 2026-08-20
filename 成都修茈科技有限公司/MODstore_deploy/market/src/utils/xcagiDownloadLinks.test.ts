import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  OFFICIAL_MANIFEST_URL,
  detectMacDownloadArch,
  fetchDownloadManifest,
  findManifestEntry,
  macArchFromQuery,
  macDownloadArchLabel,
  normalizeXcagiDownloadBase,
  resolveDownloadEntry,
  xcagiDownloadFileName,
  xcagiDownloadUrl,
  type XcagiDownloadManifest,
} from './xcagiDownloadLinks'

describe('xcagiDownloadLinks', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to the stable 1.0.0.0 dual-SKU release root', () => {
    expect(normalizeXcagiDownloadBase(undefined)).toBe('https://xiu-ci.com/xcagi-v1.0.0.0')
  })

  it('exposes the official manifest URL pinned to the stable version', () => {
    expect(OFFICIAL_MANIFEST_URL).toBe('https://xiu-ci.com/xcagi-v1.0.0.0/manifest.json')
  })

  it('builds personal and enterprise Windows URLs without offline SKU', () => {
    const base = normalizeXcagiDownloadBase('https://xiu-ci.com/releases/stable/')

    expect(xcagiDownloadUrl('personal', 'win', base)).toBe(
      'https://xiu-ci.com/releases/stable/personal/XCAGI-Personal-Setup-1.0.0.0-x64.exe',
    )
    expect(xcagiDownloadUrl('enterprise', 'win', base)).toBe(
      'https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-Setup-1.0.0.0-x64.exe',
    )
    expect(xcagiDownloadUrl('personal', 'win', base)).not.toContain('offline')
    expect(xcagiDownloadUrl('enterprise', 'win', base)).not.toContain('offline')
  })

  it('uses the stable Android 1.0.0.0 artifact names', () => {
    expect(xcagiDownloadFileName('personal', 'android')).toBe('XCAGI-Personal-Android-1.0.0.0.apk')
    expect(xcagiDownloadFileName('enterprise', 'android')).toBe('XCAGI-Enterprise-Android-1.0.0.0.apk')
  })

  it('builds personal and enterprise macOS dmg URLs for x64 and arm64', () => {
    const base = normalizeXcagiDownloadBase('https://xiu-ci.com/xcagi-v8.1.0')

    expect(xcagiDownloadFileName('personal', 'mac', '8.1.0', '1.5.0', 'x64')).toBe('XCAGI-Personal-8.1.0-mac-x64.dmg')
    expect(xcagiDownloadFileName('enterprise', 'mac', '8.1.0', '1.5.0', 'arm64')).toBe('XCAGI-Enterprise-8.1.0-mac-arm64.dmg')
    expect(xcagiDownloadUrl('personal', 'mac', base, '8.1.0', '1.5.0', 'arm64')).toBe(
      'https://xiu-ci.com/xcagi-v8.1.0/personal/XCAGI-Personal-8.1.0-mac-arm64.dmg',
    )
    expect(xcagiDownloadUrl('enterprise', 'mac', base, '8.1.0', '1.5.0', 'x64')).toBe(
      'https://xiu-ci.com/xcagi-v8.1.0/enterprise/XCAGI-Enterprise-8.1.0-mac-x64.dmg',
    )
  })

  it('macArchFromQuery reads ?macArch=', () => {
    vi.stubGlobal('window', {
      location: { search: '?macArch=arm64' },
    })
    expect(macArchFromQuery()).toBe('arm64')

    vi.stubGlobal('window', {
      location: { search: '?macArch=intel' },
    })
    expect(macArchFromQuery()).toBe('x64')
  })

  it('detectMacDownloadArch prefers query override', () => {
    vi.stubGlobal('window', {
      location: { search: '?macArch=x64' },
    })
    vi.stubGlobal('navigator', { userAgent: 'arm64 Mac' })
    expect(detectMacDownloadArch()).toBe('x64')
  })

  it('macDownloadArchLabel', () => {
    expect(macDownloadArchLabel('arm64')).toBe('Apple Silicon')
    expect(macDownloadArchLabel('x64')).toBe('Intel')
  })
})

const mockManifest: XcagiDownloadManifest = {
  schema: 'xcagi.download_manifest/v1',
  version: '1.0.0.0',
  generated_at: '2026-07-07T15:00:00Z',
  git_sha: 'abc123def456',
  channels: {
    auto_update: {
      base_url: 'https://xiu-ci.com/releases/stable',
      personal: {
        win: {
          url: 'https://xiu-ci.com/releases/stable/personal/XCAGI-Personal-Setup-1.0.0.0-x64.exe',
          filename: 'XCAGI-Personal-Setup-1.0.0.0-x64.exe',
          sha256: 'aaaa',
          size: 1000,
          platform_label: 'Windows x64',
        },
      },
      enterprise: {
        win: {
          url: 'https://xiu-ci.com/releases/stable/enterprise/XCAGI-Enterprise-Setup-1.0.0.0-x64.exe',
          filename: 'XCAGI-Enterprise-Setup-1.0.0.0-x64.exe',
          sha256: 'bbbb',
          size: 1100,
          platform_label: 'Windows x64',
        },
      },
    },
    official_download: {
      base_url: 'https://xiu-ci.com/xcagi-v1.0.0.0',
      personal: {
        win: {
          url: 'https://xiu-ci.com/xcagi-v1.0.0.0/personal/XCAGI-Personal-Setup-1.0.0.0-x64.exe',
          filename: 'XCAGI-Personal-Setup-1.0.0.0-x64.exe',
          sha256: 'aaaa',
          size: 1000,
          platform_label: 'Windows x64',
        },
        mac: [
          {
            url: 'https://xiu-ci.com/xcagi-v1.0.0.0/personal/XCAGI-Personal-1.0.0.0-mac-arm64.dmg',
            filename: 'XCAGI-Personal-1.0.0.0-mac-arm64.dmg',
            sha256: 'cccc',
            size: 2000,
            arch: 'arm64',
            platform_label: 'macOS arm64',
          },
        ],
      },
      enterprise: {
        win: {
          url: 'https://xiu-ci.com/xcagi-v1.0.0.0/enterprise/XCAGI-Enterprise-Setup-1.0.0.0-x64.exe',
          filename: 'XCAGI-Enterprise-Setup-1.0.0.0-x64.exe',
          sha256: 'bbbb',
          size: 1100,
          platform_label: 'Windows x64',
        },
      },
    },
  },
}

describe('fetchDownloadManifest', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('returns parsed manifest on HTTP 200', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => mockManifest,
      })),
    )
    const m = await fetchDownloadManifest('https://example.com/manifest.json', { force: true })
    expect(m).not.toBeNull()
    expect(m?.version).toBe('1.0.0.0')
    expect(m?.channels.official_download.personal?.win?.sha256).toBe('aaaa')
  })

  it('returns null on HTTP 404 (caller falls back to static URL)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, json: async () => null })),
    )
    const m = await fetchDownloadManifest('https://example.com/missing.json', { force: true })
    expect(m).toBeNull()
  })

  it('returns null on schema mismatch', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ schema: 'wrong', version: '1.0.0.0' }),
      })),
    )
    const m = await fetchDownloadManifest('https://example.com/manifest.json', { force: true })
    expect(m).toBeNull()
  })

  it('returns null on network error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network')
      }),
    )
    const m = await fetchDownloadManifest('https://example.com/manifest.json', { force: true })
    expect(m).toBeNull()
  })
})

describe('findManifestEntry', () => {
  it('finds Windows entry for personal SKU', () => {
    const entry = findManifestEntry(mockManifest, 'personal', 'win')
    expect(entry).not.toBeNull()
    expect(entry?.filename).toBe('XCAGI-Personal-Setup-1.0.0.0-x64.exe')
    expect(entry?.sha256).toBe('aaaa')
  })

  it('finds macOS arm64 entry', () => {
    const entry = findManifestEntry(mockManifest, 'personal', 'mac', 'arm64')
    expect(entry).not.toBeNull()
    expect(entry?.arch).toBe('arm64')
  })

  it('returns null for missing enterprise macOS', () => {
    const entry = findManifestEntry(mockManifest, 'enterprise', 'mac', 'arm64')
    expect(entry).toBeNull()
  })

  it('returns null when manifest is null', () => {
    expect(findManifestEntry(null, 'personal', 'win')).toBeNull()
  })
})

describe('resolveDownloadEntry', () => {
  it('uses manifest entry when available', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => mockManifest,
      })),
    )
    const entry = await resolveDownloadEntry('enterprise', 'win')
    expect(entry.url).toBe('https://xiu-ci.com/xcagi-v1.0.0.0/enterprise/XCAGI-Enterprise-Setup-1.0.0.0-x64.exe')
    expect(entry.sha256).toBe('bbbb')
    expect(entry.size).toBe(1100)
  })

  it('falls back to static URL when manifest fetch fails', async () => {
    // 用动态 import 拿到干净的模块(避免上一个测试的 cachedManifest 污染)
    vi.resetModules()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404, json: async () => null })),
    )
    const mod = await import('./xcagiDownloadLinks')
    const entry = await mod.resolveDownloadEntry('personal', 'win')
    expect(entry.url).toBe('https://xiu-ci.com/xcagi-v1.0.0.0/personal/XCAGI-Personal-Setup-1.0.0.0-x64.exe')
    expect(entry.sha256).toBe('')
    expect(entry.size).toBe(0)
  })
})
