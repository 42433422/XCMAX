import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  detectMacDownloadArch,
  macArchFromQuery,
  macDownloadArchLabel,
  normalizeXcagiDownloadBase,
  xcagiDownloadFileName,
  xcagiDownloadUrl,
} from './xcagiDownloadLinks'

describe('xcagiDownloadLinks', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to the v10 (10.0.0) dual-SKU release root', () => {
    expect(normalizeXcagiDownloadBase(undefined)).toBe('https://dl.xiu-ci.com/xcagi-v10.0.0')
  })

  it('builds personal and enterprise Windows URLs without offline SKU', () => {
    const base = normalizeXcagiDownloadBase('https://update.xcagi.com/releases/stable/')

    expect(xcagiDownloadUrl('personal', 'win', base)).toBe(
      'https://update.xcagi.com/releases/stable/personal/XCAGI-Personal-Setup-10.0.0-x64.exe',
    )
    expect(xcagiDownloadUrl('enterprise', 'win', base)).toBe(
      'https://update.xcagi.com/releases/stable/enterprise/XCAGI-Enterprise-Setup-10.0.0-x64.exe',
    )
    expect(xcagiDownloadUrl('personal', 'win', base)).not.toContain('offline')
    expect(xcagiDownloadUrl('enterprise', 'win', base)).not.toContain('offline')
  })

  it('uses the Android v10 (10.0.0) artifact names', () => {
    expect(xcagiDownloadFileName('personal', 'android')).toBe('XCAGI-Personal-Android-10.0.0.apk')
    expect(xcagiDownloadFileName('enterprise', 'android')).toBe(
      'XCAGI-Enterprise-Android-10.0.0.apk',
    )
  })

  it('builds personal and enterprise macOS dmg URLs for x64 and arm64', () => {
    const base = normalizeXcagiDownloadBase('https://dl.xiu-ci.com/xcagi-v8.1.0')

    expect(xcagiDownloadFileName('personal', 'mac', '8.1.0', '1.5.0', 'x64')).toBe(
      'XCAGI-Personal-8.1.0-mac-x64.dmg',
    )
    expect(xcagiDownloadFileName('enterprise', 'mac', '8.1.0', '1.5.0', 'arm64')).toBe(
      'XCAGI-Enterprise-8.1.0-mac-arm64.dmg',
    )
    expect(xcagiDownloadUrl('personal', 'mac', base, '8.1.0', '1.5.0', 'arm64')).toBe(
      'https://dl.xiu-ci.com/xcagi-v8.1.0/personal/XCAGI-Personal-8.1.0-mac-arm64.dmg',
    )
    expect(xcagiDownloadUrl('enterprise', 'mac', base, '8.1.0', '1.5.0', 'x64')).toBe(
      'https://dl.xiu-ci.com/xcagi-v8.1.0/enterprise/XCAGI-Enterprise-8.1.0-mac-x64.dmg',
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
