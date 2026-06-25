import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DesktopRuntimeView from './DesktopRuntimeView.vue'

describe('DesktopRuntimeView', () => {
  const originalXcagiDesktop = (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop

  beforeEach(() => {
    (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })

  afterEach(() => {
    (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = originalXcagiDesktop
  })

  function mockFetch(statusPayload: unknown, modelsPayload: { models: unknown[] }) {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/api/desktop/status') {
        return Promise.resolve({
          ok: true,
          json: async () => statusPayload,
        } as Response)
      }
      if (url === '/api/desktop/models') {
        return Promise.resolve({
          ok: true,
          json: async () => modelsPayload,
        } as Response)
      }
      return Promise.resolve({ ok: true, json: async () => ({}) } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('renders the page heading', () => {
    mockFetch({ desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' }, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    expect(wrapper.find('h1').text()).toBe('桌面运行时')
  })

  it('renders refresh button', () => {
    mockFetch({ desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' }, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    const buttons = wrapper.findAll('button')
    const refreshBtn = buttons.find((b) => b.text().includes('刷新状态'))
    expect(refreshBtn).toBeTruthy()
  })

  it('does not render check updates button when not desktop shell', () => {
    mockFetch({ desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' }, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    const buttons = wrapper.findAll('button')
    const updateBtn = buttons.find((b) => b.text().includes('检查桌面更新'))
    expect(updateBtn).toBeUndefined()
  })

  it('renders check updates button when desktop shell is available', () => {
    (window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {
      checkForUpdates: vi.fn().mockResolvedValue({ ok: true }),
      onUpdateEvent: vi.fn(),
    }
    mockFetch({ desktopMode: true, dataDir: '', database: '', modsDir: '', modelsDir: '' }, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    const buttons = wrapper.findAll('button')
    const updateBtn = buttons.find((b) => b.text().includes('检查桌面更新'))
    expect(updateBtn).toBeTruthy()
  })

  it('shows loading text before status loads', () => {
    mockFetch({ desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' }, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    expect(wrapper.text()).toContain('正在加载...')
  })

  it('loads and displays status on mount', async () => {
    const statusPayload = {
      desktopMode: true,
      dataDir: '/data',
      database: 'sqlite',
      modsDir: '/mods',
      modelsDir: '/models',
      storageMode: 'local_sqlite',
      databaseUrlRedacted: 'sqlite:///****',
    }
    mockFetch(statusPayload, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('/data')
    expect(wrapper.text()).toContain('sqlite')
    expect(wrapper.text()).toContain('本地 SQLite')
  })

  it('displays remote_postgresql storage mode label', async () => {
    const statusPayload = {
      desktopMode: false,
      dataDir: '/data',
      database: 'pg',
      modsDir: '/mods',
      modelsDir: '/models',
      storageMode: 'remote_postgresql',
    }
    mockFetch(statusPayload, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('远程 PostgreSQL')
  })

  it('displays "—" for unknown storage mode', async () => {
    const statusPayload = {
      desktopMode: false,
      dataDir: '/data',
      database: 'pg',
      modsDir: '/mods',
      modelsDir: '/models',
      storageMode: 'unknown_mode',
    }
    mockFetch(statusPayload, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('unknown_mode')
  })

  it('displays "—" when storageMode is undefined', async () => {
    const statusPayload = {
      desktopMode: false,
      dataDir: '/data',
      database: 'pg',
      modsDir: '/mods',
      modelsDir: '/models',
    }
    mockFetch(statusPayload, { models: [] })
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    const dds = wrapper.findAll('dd')
    const storageDd = dds.find((dd) => dd.text() === '—')
    expect(storageDd).toBeTruthy()
  })

  it('displays desktopMode as "是" or "否"', async () => {
    mockFetch(
      { desktopMode: true, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('是')
  })

  it('displays "暂无已安装模型" when models list is empty', async () => {
    mockFetch(
      { desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('暂无已安装模型')
  })

  it('displays models list when models are present', async () => {
    const models = [
      { name: 'modelA', version: '1.0', path: '/models/a' },
      { name: 'modelB', version: '2.0', path: '/models/b' },
    ]
    mockFetch(
      { desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('modelA')
    expect(wrapper.text()).toContain('modelB')
    expect(wrapper.findAll('li').length).toBeGreaterThanOrEqual(2)
  })

  it('refreshes status when refresh button is clicked', async () => {
    const fetchMock = mockFetch(
      { desktopMode: false, dataDir: '/old', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    fetchMock.mockClear()
    const refreshBtn = wrapper.findAll('button').find((b) => b.text().includes('刷新状态'))!
    await refreshBtn.trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalled()
  })

  it('checks for updates when check updates button is clicked', async () => {
    const checkForUpdates = vi.fn().mockResolvedValue({ ok: true, version: '1.2.3' })
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {
      checkForUpdates,
      onUpdateEvent: vi.fn(),
    }
    mockFetch(
      { desktopMode: true, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    const updateBtn = wrapper.findAll('button').find((b) => b.text().includes('检查桌面更新'))!
    await updateBtn.trigger('click')
    await flushPromises()
    expect(checkForUpdates).toHaveBeenCalled()
    expect(wrapper.find('pre').exists()).toBe(true)
  })

  it('subscribes to update events on mount when desktop shell available', async () => {
    const onUpdateEvent = vi.fn()
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {
      checkForUpdates: vi.fn(),
      onUpdateEvent,
    }
    mockFetch(
      { desktopMode: true, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(onUpdateEvent).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('renders update events section when events exist', async () => {
    const onUpdateEvent = vi.fn()
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {
      checkForUpdates: vi.fn(),
      onUpdateEvent,
    }
    mockFetch(
      { desktopMode: true, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    const cb = onUpdateEvent.mock.calls[0][0] as (event: unknown) => void
    cb({ type: 'update', version: '2.0' })
    await flushPromises()
    expect(wrapper.find('pre').exists()).toBe(true)
    expect(wrapper.find('pre').text()).toContain('update')
  })

  it('renders databaseUrlRedacted when present', async () => {
    mockFetch(
      {
        desktopMode: false,
        dataDir: '',
        database: '',
        modsDir: '',
        modelsDir: '',
        databaseUrlRedacted: 'sqlite:///****',
      },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('sqlite:///****')
  })

  it('renders "—" when databaseUrlRedacted is absent', async () => {
    mockFetch(
      { desktopMode: false, dataDir: '', database: '', modsDir: '', modelsDir: '' },
      { models: [] },
    )
    const wrapper = mount(DesktopRuntimeView)
    await flushPromises()
    expect(wrapper.text()).toContain('—')
  })
})
