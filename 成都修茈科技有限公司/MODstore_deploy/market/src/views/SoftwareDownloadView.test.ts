import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SoftwareDownloadView from './SoftwareDownloadView.vue'

const routeState = vi.hoisted(() => ({ name: 'download' as string }))
const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  back: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => routerMock,
}))

const originalUserAgent = window.navigator.userAgent
const originalHistoryLength = window.history.length
const originalLocation = window.location
let locationAssign: ReturnType<typeof vi.fn>

function installMatchMedia(matches = false) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches,
      media: '(max-width: 768px)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

function installUserAgent(value: string) {
  Object.defineProperty(window.navigator, 'userAgent', {
    configurable: true,
    value,
  })
}

function installHistoryLength(value: number) {
  Object.defineProperty(window.history, 'length', {
    configurable: true,
    value,
  })
}

function jsonResponse(data: Record<string, unknown>) {
  return {
    ok: true,
    headers: { get: vi.fn(() => 'application/json') },
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response
}

function textResponse() {
  return {
    ok: true,
    headers: { get: vi.fn(() => 'text/html; charset=utf-8') },
    json: vi.fn(),
  } as unknown as Response
}

function findButton(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  expect(button, `button containing ${text}`).toBeTruthy()
  return button!
}

async function mountView() {
  const wrapper = mount(SoftwareDownloadView)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  routeState.name = 'download'
  routerMock.push.mockReset()
  routerMock.back.mockReset()
  delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
  locationAssign = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { assign: locationAssign },
  })
  installHistoryLength(originalHistoryLength)
  installUserAgent(originalUserAgent)
  installMatchMedia(false)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: originalLocation,
  })
  delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
  installHistoryLength(originalHistoryLength)
  installUserAgent(originalUserAgent)
  document.body.innerHTML = ''
})

describe('SoftwareDownloadView', () => {
  it('loads the release manifest and downloads the desktop installer with an anchor', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          download_version: '11.2.3',
          android_version: '5.6.7',
          win_installer_mb: 777,
          cos_base_url: 'https://cdn.example.com/releases',
        }),
      ),
    )
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = await mountView()

    expect(fetch).toHaveBeenCalledWith('/download-release.json', { cache: 'no-store' })
    expect(wrapper.text()).toContain('XC 11.2.3 · 个人版')
    expect(wrapper.text()).toContain('安装包约 777 MB')

    await findButton(wrapper, 'Windows 64 位').trigger('click')

    expect(anchorClick).toHaveBeenCalledTimes(1)
    expect(locationAssign).not.toHaveBeenCalled()
  })

  it('uses the desktop native download bridge before falling back to the browser anchor', async () => {
    const nativeDownload = vi.fn().mockResolvedValue({ ok: true })
    Object.defineProperty(window, 'xcagiDesktop', {
      configurable: true,
      value: { isDesktop: true, downloadFile: nativeDownload },
    })
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = await mountView()
    await findButton(wrapper, 'Windows 64 位').trigger('click')
    await flushPromises()

    expect(nativeDownload).toHaveBeenCalledWith({
      url: 'https://dl.xiu-ci.com/xcagi-v10.0.0/personal/XCAGI-Personal-Setup-10.0.0-x64.exe',
      filename: 'XCAGI-Personal-Setup-10.0.0-x64.exe',
    })
    expect(anchorClick).not.toHaveBeenCalled()
  })

  it('falls back to browser download when the desktop bridge cannot start the download', async () => {
    Object.defineProperty(window, 'xcagiDesktop', {
      configurable: true,
      value: { isDesktop: true, downloadFile: vi.fn().mockResolvedValue({ ok: false }) },
    })
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = await mountView()
    await findButton(wrapper, 'Windows 64 位').trigger('click')
    await flushPromises()

    expect(anchorClick).toHaveBeenCalledTimes(1)
  })

  it('ignores non-json manifests, switches editions, and sends Android downloads through location', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(textResponse()))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('XC 10.0.0 · 个人版')

    await findButton(wrapper, '企业版').trigger('click')
    expect(wrapper.text()).toContain('XC 10.0.0 · 企业版')
    expect(wrapper.text()).toContain('完整 AI 创作与 ERP 能力')

    await findButton(wrapper, 'Android').trigger('click')
    expect(wrapper.text()).toContain('Android 客户端')
    expect(wrapper.text()).toContain('Android · 企业版')
    expect(wrapper.text()).toContain('隐私政策')

    await findButton(wrapper, 'Android · 企业版').trigger('click')
    expect(locationAssign).toHaveBeenCalledTimes(1)
  })

  it('starts in Android mode on mobile or Android user agents and exposes the dock actions', async () => {
    installMatchMedia(true)
    installUserAgent('Mozilla/5.0 Android')

    const wrapper = await mountView()

    expect(wrapper.classes()).toContain('sd--mobile')
    expect(wrapper.classes()).toContain('sd--android-ua')
    expect(wrapper.text()).toContain('XC 10.0.0')
    expect(wrapper.find('.sd-dock').exists()).toBe(true)

    await wrapper.find('.sd-dock button').trigger('click')
    expect(locationAssign).toHaveBeenCalledTimes(1)
  })

  it('handles workbench, browser history, and hard fallback back navigation', async () => {
    routeState.name = 'workbench-download'
    let wrapper = await mountView()
    await findButton(wrapper, '返回').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'workbench-home' })
    wrapper.unmount()

    routeState.name = 'download'
    installHistoryLength(3)
    wrapper = await mountView()
    await findButton(wrapper, '返回').trigger('click')
    expect(routerMock.back).toHaveBeenCalledTimes(1)
    wrapper.unmount()

    installHistoryLength(1)
    wrapper = await mountView()
    await findButton(wrapper, '返回').trigger('click')
    expect(locationAssign).toHaveBeenCalledWith('/index.html')
  })
})
