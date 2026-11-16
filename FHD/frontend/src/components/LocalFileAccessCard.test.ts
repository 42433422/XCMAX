import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import LocalFileAccessCard from './LocalFileAccessCard.vue'
import localFileAccessApi from '@/api/localFileAccess'

vi.mock('@/api/localFileAccess', () => ({
  default: {
    status: vi.fn(),
    createGrant: vi.fn(),
    revokeGrant: vi.fn(),
    syncGrant: vi.fn(),
    grantDetail: vi.fn(),
  },
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(() => Promise.resolve()),
  appConfirm: vi.fn(() => Promise.resolve(true)),
}))

const status = (overrides: Record<string, unknown> = {}) => ({
  desktop: true,
  full_disk_access: 'granted',
  grants: [],
  ...overrides,
})

const grant = {
  id: 3,
  mode: 'folder',
  root_path: '/Users/me/Docs',
  display_name: 'Docs',
  is_active: true,
  scan_status: 'ready',
  indexed_count: 4,
  skipped_count: 1,
  error_count: 0,
}

function installDesktop(overrides: Record<string, unknown> = {}) {
  ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {
    chooseDirectory: vi.fn(async () => ({ canceled: false, paths: ['/Users/me/Docs'] })),
    openPrivacySettings: vi.fn(async () => ({ ok: true })),
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(localFileAccessApi.status).mockReset().mockResolvedValue(status())
  vi.mocked(localFileAccessApi.createGrant).mockReset()
  vi.mocked(localFileAccessApi.revokeGrant).mockReset().mockResolvedValue({} as never)
  vi.mocked(localFileAccessApi.syncGrant).mockReset().mockResolvedValue({} as never)
  delete (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop
})

it('tells browser users this capability is desktop-only', async () => {
  const wrapper = mount(LocalFileAccessCard)
  await flushPromises()
  expect(wrapper.text()).toContain('仅桌面端可用')
  expect(localFileAccessApi.status).not.toHaveBeenCalled()
})

it('shows authorized folders with counters', async () => {
  installDesktop()
  vi.mocked(localFileAccessApi.status).mockResolvedValue(status({ grants: [grant] }) as never)
  const wrapper = mount(LocalFileAccessCard)
  await flushPromises()
  expect(wrapper.text()).toContain('已授权 1 处')
  expect(wrapper.text()).toContain('/Users/me/Docs')
  expect(wrapper.text()).toContain('已索引 4')
  expect(wrapper.text()).toContain('完全磁盘访问：已开启')
})

it('authorizes the picked folder and refreshes state', async () => {
  installDesktop()
  vi.mocked(localFileAccessApi.createGrant).mockResolvedValue(grant as never)
  const wrapper = mount(LocalFileAccessCard)
  await flushPromises()
  const button = wrapper.findAll('button').find((item) => item.text().includes('选择文件夹授权'))
  await button!.trigger('click')
  await flushPromises()
  expect(localFileAccessApi.createGrant).toHaveBeenCalledWith('folder', '/Users/me/Docs')
  expect(localFileAccessApi.status).toHaveBeenCalledTimes(2)
})

it('guides the user to system settings when full disk access is denied', async () => {
  const openPrivacySettings = vi.fn(async () => ({ ok: true }))
  installDesktop({ openPrivacySettings })
  vi.mocked(localFileAccessApi.status).mockResolvedValue(
    status({ full_disk_access: 'denied' }) as never,
  )
  const wrapper = mount(LocalFileAccessCard)
  await flushPromises()
  const button = wrapper.findAll('button').find((item) => item.text().includes('去系统设置'))
  await button!.trigger('click')
  await flushPromises()
  expect(openPrivacySettings).toHaveBeenCalled()
  expect(localFileAccessApi.createGrant).not.toHaveBeenCalled()
})

it('revokes after confirmation', async () => {
  installDesktop()
  vi.mocked(localFileAccessApi.status).mockResolvedValue(status({ grants: [grant] }) as never)
  const wrapper = mount(LocalFileAccessCard)
  await flushPromises()
  const button = wrapper.findAll('button').find((item) => item.text() === '撤销')
  await button!.trigger('click')
  await flushPromises()
  expect(localFileAccessApi.revokeGrant).toHaveBeenCalledWith(3)
})
