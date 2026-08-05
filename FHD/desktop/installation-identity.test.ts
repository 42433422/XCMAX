import { describe, expect, it } from 'vitest'
import {
  CANONICAL_MAC_APP_PATH,
  macAppBundlePathFromExecutable,
  resolveDesktopInstallIdentity,
} from './installation-identity'

describe('desktop installation identity', () => {
  it('resolves the outer macOS app bundle from the executable path', () => {
    expect(
      macAppBundlePathFromExecutable('/Applications/XCAGI.app/Contents/MacOS/XCAGI'),
    ).toBe('/Applications/XCAGI.app')
  })

  it('marks the official Applications copy as self-update eligible', () => {
    expect(
      resolveDesktopInstallIdentity({
        platform: 'darwin',
        isPackaged: true,
        executablePath: '/Applications/XCAGI.app/Contents/MacOS/XCAGI',
      }),
    ).toMatchObject({
      appPath: CANONICAL_MAC_APP_PATH,
      canonicalAppPath: CANONICAL_MAC_APP_PATH,
      isCanonical: true,
      canSelfUpdate: true,
    })
  })

  it('does not let a mounted or temporary macOS copy self-update over the official app', () => {
    expect(
      resolveDesktopInstallIdentity({
        platform: 'darwin',
        isPackaged: true,
        executablePath: '/private/tmp/XCAGI.app/Contents/MacOS/XCAGI',
      }),
    ).toMatchObject({
      appPath: '/private/tmp/XCAGI.app',
      isCanonical: false,
      canSelfUpdate: false,
    })
  })

  it('keeps Windows installed builds update eligible', () => {
    expect(
      resolveDesktopInstallIdentity({
        platform: 'win32',
        isPackaged: true,
        executablePath: 'C:\\Program Files\\XCAGI\\XCAGI.exe',
      }),
    ).toMatchObject({ isCanonical: true, canSelfUpdate: true })
  })
})
