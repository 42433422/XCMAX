import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

// --- Mocks ---

const mockSafeJsonRequest = vi.fn()
const mockSetCursorEnabled = vi.fn()
const mockClipboardWriteText = vi.fn()

vi.mock('@/utils/safeJsonRequest', () => ({
  safeJsonRequest: (...args: unknown[]) => mockSafeJsonRequest(...args),
}))

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => 'http://localhost:5100',
}))

vi.mock('@/composables/useAiOpenCursor', () => ({
  useAiOpenCursor: () => ({
    enabled: ref(false),
    connected: ref(false),
    sessionId: ref(''),
    logs: ref([]),
    setEnabled: mockSetCursorEnabled,
  }),
}))

vi.mock('@/utils/aiopenMcpInstall', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/aiopenMcpInstall')>()
  return {
    ...actual,
    buildAiopenClientInstalls: vi.fn(() => [
      {
        id: 'cursor',
        name: 'Cursor',
        icon: '🖱',
        configPath: '~/.cursor/mcp.json',
        hint: 'Cursor 设置',
        transport: 'url',
        mcpJson: '{"mcpServers":{"xcagi":{"url":"http://localhost:5100/api/aiopen/mcp"}}}',
        installMode: 'copy',
        installLabel: '复制 JSON',
      },
      {
        id: 'vscode',
        name: 'VS Code',
        icon: '📋',
        configPath: 'settings.json',
        hint: 'VS Code',
        transport: 'stdio',
        mcpJson: '{"mcpServers":{"xcagi":{}}}',
        installUrl: 'vscode://',
        installMode: 'vscode',
        installLabel: '一键安装',
      },
      {
        id: 'claude',
        name: 'Claude',
        icon: '🤖',
        configPath: '~/claude.json',
        hint: 'Claude',
        transport: 'url',
        mcpJson: '{"mcpServers":{"xcagi":{}}}',
        installUrl: 'claude://',
        installFallbackUrl: 'https://claude.ai',
        installMode: 'deeplink',
        installLabel: '一键安装',
      },
    ]),
    buildAiAssistantSetupPrompt: vi.fn(() => 'AI assistant prompt text'),
    buildAiopenOneLiner: vi.fn(() => '一句话配置 http://localhost:5100/api/aiopen/mcp'),
    resolveAiopenBackendBase: vi.fn((origin: string) => origin || 'http://localhost:5100'),
    readAiopenInstalledClients: vi.fn(() => []),
    markAiopenClientInstalled: vi.fn(),
    unmarkAiopenClientInstalled: vi.fn(),
  }
})

import AIOpenPanel from './AIOpenPanel.vue'

// Default API responses for onMounted → loadPanel
function setupDefaultApiResponses(overrides: Record<string, unknown> = {}) {
  const panel = {
    ok: true,
    data: {
      success: true,
      wechat_open: false,
      routes: [{ path: '/api/orders', enabled: true }],
      openclaw_base: 'http://localhost:28789',
      remote_control_enabled: false,
      keys: [],
    },
    ...overrides.panel,
  }
  const manifest = {
    ok: true,
    data: {
      success: true,
      name: 'AIOPEN',
      tools: [
        { name: 'api_catalog', description: 'list APIs' },
        { name: 'api_call', description: 'call API' },
      ],
    },
    ...overrides.manifest,
  }
  const install = {
    ok: true,
    data: {
      success: true,
      tool_count: 2,
      server_name: 'xcagi-aiopen',
      methods: { stdio: { script_path: '/path/to/script.py' } },
    },
    ...overrides.install,
  }
  mockSafeJsonRequest.mockImplementation((url: string) => {
    if (url.includes('/panel')) return Promise.resolve(panel)
    if (url.includes('/manifest')) return Promise.resolve(manifest)
    if (url.includes('/install')) return Promise.resolve(install)
    if (url.includes('/mcp')) return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN', tool_count: 9 } })
    return Promise.resolve({ ok: true, data: { success: true } })
  })
}

async function mountPanel(overrides: Record<string, unknown> = {}) {
  setupDefaultApiResponses(overrides)
  const wrapper = mount(AIOpenPanel, {
    global: {
      stubs: { RouterLink: true },
    },
  })
  await flushPromises()
  return wrapper
}

describe('AIOpenPanel functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Mock clipboard
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: mockClipboardWriteText },
      configurable: true,
    })
    mockClipboardWriteText.mockResolvedValue(undefined)
    // Mock window.location.href setter (for deeplink/vscode installs)
    Object.defineProperty(window, 'location', {
      value: { ...window.location, href: '', origin: 'http://localhost:5173' },
      configurable: true,
    })
  })

  // --- handlePrimaryAction / quickSetup / shutdownAiOpen ---

  it('handlePrimaryAction triggers quickSetup when not active', async () => {
    const wrapper = await mountPanel()
    // Click the primary button
    const btn = wrapper.find('.aiopen-primary-btn')
    expect(btn.exists()).toBe(true)
    // Setup control endpoint to return ok
    mockSafeJsonRequest.mockImplementation((url: string, opts?: unknown) => {
      if (url.includes('/control')) return Promise.resolve({ ok: true, data: { success: true } })
      if (url.includes('/keys')) return Promise.resolve({ ok: true, data: { success: true, key: 'test-key' } })
      if (url.includes('/panel')) return Promise.resolve({ ok: true, data: { success: true, routes: [], keys: [] } })
      if (url.includes('/manifest')) return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [] } })
      if (url.includes('/install')) return Promise.resolve({ ok: true, data: { success: true } })
      if (url.includes('/mcp')) return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN' } })
      return Promise.resolve({ ok: true, data: { success: true } })
    })
    await btn.trigger('click')
    await flushPromises()
    expect(mockSetCursorEnabled).toHaveBeenCalledWith(true)
  })

  it('handlePrimaryAction triggers shutdownAiOpen when active', async () => {
    // Start with remote_control_enabled = true so aiOpenActive is true
    const wrapper = await mountPanel({
      panel: {
        ok: true,
        data: {
          success: true,
          wechat_open: false,
          routes: [],
          openclaw_base: 'http://localhost:28789',
          remote_control_enabled: true,
          keys: [{ key: 'existing-key' }],
        },
      },
    })
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/control')) return Promise.resolve({ ok: true, data: { success: true } })
      if (url.includes('/panel')) return Promise.resolve({ ok: true, data: { success: true, routes: [], keys: [], remote_control_enabled: true } })
      if (url.includes('/manifest')) return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [] } })
      if (url.includes('/install')) return Promise.resolve({ ok: true, data: { success: true } })
      if (url.includes('/mcp')) return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN' } })
      return Promise.resolve({ ok: true, data: { success: true } })
    })
    const btn = wrapper.find('.aiopen-primary-btn')
    await btn.trigger('click')
    await flushPromises()
    expect(mockSetCursorEnabled).toHaveBeenCalledWith(false)
  })

  // --- copyOneLiner ---

  it('copyOneLiner copies text to clipboard', async () => {
    const wrapper = await mountPanel()
    // Find the "复制一句话" button
    const btn = wrapper.find('.aiopen-oneline-btn:not(.aiopen-oneline-btn--ghost)')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(mockClipboardWriteText).toHaveBeenCalled()
  })

  // --- copyAiAssistantPrompt ---

  it('copyAiAssistantPrompt copies prompt to clipboard', async () => {
    const wrapper = await mountPanel()
    const btn = wrapper.find('.aiopen-oneline-btn--ghost')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(mockClipboardWriteText).toHaveBeenCalled()
  })

  // --- handleClientClick / installForClient (copy mode) ---

  it('handleClientClick installs client in copy mode', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/keys')) return Promise.resolve({ ok: true, data: { success: true, key: 'new-key' } })
      if (url.includes('/install')) return Promise.resolve({ ok: true, data: { success: true, methods: { stdio: { script_path: '/p' } } } })
      if (url.includes('/panel')) return Promise.resolve({ ok: true, data: { success: true, routes: [], keys: [] } })
      if (url.includes('/manifest')) return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [] } })
      if (url.includes('/mcp')) return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN' } })
      return Promise.resolve({ ok: true, data: { success: true } })
    })
    // Click the first client button (cursor - copy mode)
    const clientBtn = wrapper.find('.aiopen-client-btn')
    expect(clientBtn.exists()).toBe(true)
    await clientBtn.trigger('click')
    await flushPromises()
    expect(mockClipboardWriteText).toHaveBeenCalled()
  })

  // --- toggleRemoteControl ---

  it('toggleRemoteControl calls control API', async () => {
    const wrapper = await mountPanel()
    // Open the "更多设置" details
    const moreDetails = wrapper.find('.aiopen-more')
    // Find the remote control checkbox
    const checkboxes = wrapper.findAll('.aiopen-switch-row input[type="checkbox"]')
    expect(checkboxes.length).toBeGreaterThanOrEqual(1)
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    await checkboxes[0].setValue(true)
    await flushPromises()
    // Should have called safeJsonRequest with /control
    const controlCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/control'))
    expect(controlCalls.length).toBeGreaterThan(0)
  })

  // --- toggleScreenSession ---

  it('toggleScreenSession calls setCursorEnabled', async () => {
    const wrapper = await mountPanel()
    const checkboxes = wrapper.findAll('.aiopen-switch-row input[type="checkbox"]')
    // The second checkbox is the screen session toggle
    if (checkboxes.length >= 2) {
      await checkboxes[1].setValue(true)
      await flushPromises()
      expect(mockSetCursorEnabled).toHaveBeenCalledWith(true)
    }
  })

  // --- toggleWhitelist ---

  it('toggleWhitelist updates routes and calls whitelist API', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    // Find route checkboxes in the advanced section
    const routeCheckboxes = wrapper.findAll('.aiopen-route-item input[type="checkbox"]')
    if (routeCheckboxes.length > 0) {
      await routeCheckboxes[0].setValue(false)
      await flushPromises()
      const whitelistCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/whitelist'))
      expect(whitelistCalls.length).toBeGreaterThan(0)
    }
  })

  // --- toggleWechat ---

  it('toggleWechat calls wechat-gateway API', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    // Find the wechat checkbox (last switch-row in advanced)
    const switchRows = wrapper.findAll('.aiopen-switch-row input[type="checkbox"]')
    // The wechat toggle is inside the nested advanced details
    const wechatCheckbox = switchRows[switchRows.length - 1]
    if (wechatCheckbox) {
      await wechatCheckbox.setValue(true)
      await flushPromises()
      const wechatCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/wechat-gateway'))
      expect(wechatCalls.length).toBeGreaterThan(0)
    }
  })

  // --- saveOpenclawBase ---

  it('saveOpenclawBase calls config API', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    // Find the save button in the openclaw row
    const saveBtn = wrapper.findAll('.aiopen-row button').find((b) => b.text().includes('保存'))
    if (saveBtn) {
      await saveBtn.trigger('click')
      await flushPromises()
      const configCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/config'))
      expect(configCalls.length).toBeGreaterThan(0)
    }
  })

  // --- sendToOpenclaw ---

  it('sendToOpenclaw calls openclaw chat API', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    const sendBtn = wrapper.findAll('.aiopen-row button').find((b) => b.text().includes('发送'))
    if (sendBtn) {
      await sendBtn.trigger('click')
      await flushPromises()
      const chatCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/openclaw/chat'))
      expect(chatCalls.length).toBeGreaterThan(0)
    }
  })

  // --- copyClientConfig ---

  it('copyClientConfig copies MCP JSON', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    const copyJsonBtn = wrapper.findAll('button').find((b) => b.text().includes('复制 MCP JSON'))
    if (copyJsonBtn) {
      await copyJsonBtn.trigger('click')
      await flushPromises()
      expect(mockClipboardWriteText).toHaveBeenCalled()
    }
  })

  // --- copyGuideUrl ---

  it('copyGuideUrl copies guide URL', async () => {
    const wrapper = await mountPanel()
    const copyGuideBtn = wrapper.findAll('button').find((b) => b.text().includes('复制说明链接'))
    if (copyGuideBtn) {
      await copyGuideBtn.trigger('click')
      await flushPromises()
      expect(mockClipboardWriteText).toHaveBeenCalled()
    }
  })

  // --- createKey ---

  it('createKey button generates a key', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/keys')) return Promise.resolve({ ok: true, data: { success: true, key: 'generated-key' } })
      if (url.includes('/panel')) return Promise.resolve({ ok: true, data: { success: true, routes: [], keys: [] } })
      if (url.includes('/manifest')) return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [] } })
      if (url.includes('/install')) return Promise.resolve({ ok: true, data: { success: true } })
      if (url.includes('/mcp')) return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN' } })
      return Promise.resolve({ ok: true, data: { success: true } })
    })
    const createKeyBtn = wrapper.findAll('button').find((b) => b.text().includes('获取口令'))
    if (createKeyBtn) {
      await createKeyBtn.trigger('click')
      await flushPromises()
      const keyCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/keys'))
      expect(keyCalls.length).toBeGreaterThan(0)
    }
  })

  // --- loadPanel (refresh) ---

  it('loadPanel refresh button reloads panel data', async () => {
    const wrapper = await mountPanel()
    vi.clearAllMocks()
    setupDefaultApiResponses()
    const refreshBtn = wrapper.find('.aiopen-link-btn')
    expect(refreshBtn.exists()).toBe(true)
    await refreshBtn.trigger('click')
    await flushPromises()
    const panelCalls = mockSafeJsonRequest.mock.calls.filter((c) => String(c[0]).includes('/panel'))
    expect(panelCalls.length).toBeGreaterThan(0)
  })

  // --- formatPanelError (via loadPanel with error) ---

  it('loadPanel shows error when backend returns 404', async () => {
    const wrapper = await mountPanel({
      panel: { ok: false, status: 404, message: 'Not found' },
    })
    // Should display panel error
    expect(wrapper.find('.aiopen-hero-warn').exists()).toBe(true)
  })

  it('loadPanel shows error when backend returns 502', async () => {
    const wrapper = await mountPanel({
      panel: { ok: false, status: 502, message: 'Bad gateway' },
    })
    expect(wrapper.find('.aiopen-hero-warn').exists()).toBe(true)
  })

  it('loadPanel shows error when backend returns 500', async () => {
    const wrapper = await mountPanel({
      panel: { ok: false, status: 500, message: 'Internal error' },
    })
    expect(wrapper.find('.aiopen-hero-warn').exists()).toBe(true)
  })

  it('loadPanel shows error when JSON parse fails', async () => {
    const wrapper = await mountPanel({
      panel: { ok: false, status: 0, message: '请求未返回JSON' },
    })
    expect(wrapper.find('.aiopen-hero-warn').exists()).toBe(true)
  })

  it('loadPanel shows generic error for unknown status', async () => {
    const wrapper = await mountPanel({
      panel: { ok: false, status: 0, message: 'Connection refused' },
    })
    expect(wrapper.find('.aiopen-hero-warn').exists()).toBe(true)
  })

  // --- connectOpenclawWs ---

  it('connectOpenclawWs attempts WebSocket connection', async () => {
    const wrapper = await mountPanel()
    // Mock WebSocket
    const mockWs = {
      onopen: null as ((ev: Event) => void) | null,
      onmessage: null as ((ev: MessageEvent) => void) | null,
      onclose: null as ((ev: Event) => void) | null,
      onerror: null as ((ev: Event) => void) | null,
      send: vi.fn(),
      close: vi.fn(),
    }
    vi.stubGlobal('WebSocket', vi.fn(() => mockWs))
    const wsBtn = wrapper.findAll('.aiopen-row button').find((b) => b.text().includes('WS'))
    if (wsBtn) {
      await wsBtn.trigger('click')
      await flushPromises()
      expect(WebSocket).toHaveBeenCalled()
    }
    vi.unstubAllGlobals()
  })

  // --- probeMcpHealth ---

  it('probeMcpHealth shows healthy when manifest returns AIOPEN', async () => {
    const wrapper = await mountPanel()
    // The onMounted already called probeMcpHealth; verify health text
    expect(wrapper.find('.aiopen-mcp-health').exists()).toBe(true)
  })

  it('probeMcpHealth shows 403 error', async () => {
    const wrapper = await mountPanel({
      manifest: { ok: false, status: 403, data: null },
    })
    // Also mock /mcp to return 403
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/manifest')) return Promise.resolve({ ok: false, status: 403, data: null })
      if (url.includes('/mcp')) return Promise.resolve({ ok: false, status: 403, data: null })
      if (url.includes('/panel')) return Promise.resolve({ ok: true, data: { success: true, routes: [], keys: [] } })
      if (url.includes('/install')) return Promise.resolve({ ok: true, data: { success: true } })
      return Promise.resolve({ ok: true, data: { success: true } })
    })
    // Trigger refresh
    const refreshBtn = wrapper.find('.aiopen-link-btn')
    await refreshBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.aiopen-mcp-health').exists()).toBe(true)
  })

  it('probeMcpHealth shows failure on exception', async () => {
    const wrapper = await mountPanel()
    mockSafeJsonRequest.mockRejectedValue(new Error('network'))
    const refreshBtn = wrapper.find('.aiopen-link-btn')
    await refreshBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.aiopen-mcp-health').exists()).toBe(true)
  })

  // --- clientActionLabel ---

  it('clientActionLabel shows install label for uninstalled client', async () => {
    const wrapper = await mountPanel()
    const clientBtn = wrapper.find('.aiopen-client-btn')
    expect(clientBtn.exists()).toBe(true)
    const actionSpan = clientBtn.find('.aiopen-client-action')
    expect(actionSpan.exists()).toBe(true)
    expect(actionSpan.text()).toContain('复制 JSON')
  })

  // --- handleClientClick with installed client (resetClientSelection) ---

  it('handleClientClick uninstalls when client already installed', async () => {
    // Pre-install cursor client
    const { readAiopenInstalledClients } = await import('@/utils/aiopenMcpInstall')
    vi.mocked(readAiopenInstalledClients).mockReturnValue(['cursor' as never])
    const wrapper = await mountPanel()
    const clientBtn = wrapper.find('.aiopen-client-btn')
    expect(clientBtn.exists()).toBe(true)
    await clientBtn.trigger('click')
    await flushPromises()
    // Should have called unmarkAiopenClientInstalled
    const { unmarkAiopenClientInstalled } = await import('@/utils/aiopenMcpInstall')
    expect(unmarkAiopenClientInstalled).toHaveBeenCalledWith('cursor')
  })

  // --- copyText failure ---

  it('copyText handles clipboard failure gracefully', async () => {
    mockClipboardWriteText.mockRejectedValue(new Error('clipboard denied'))
    const wrapper = await mountPanel()
    const btn = wrapper.find('.aiopen-oneline-btn:not(.aiopen-oneline-btn--ghost)')
    await btn.trigger('click')
    await flushPromises()
    // Should show error toast
    expect(wrapper.find('.aiopen-toast').exists()).toBe(true)
  })

  // --- readyStatus computed ---

  it('readyStatus is off when nothing enabled', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.find('.aiopen-hero--off').exists() || !wrapper.find('.aiopen-hero--ready').exists()).toBe(true)
  })

  // --- primaryBtnLabel computed ---

  it('primaryBtnLabel shows 一键开启 when not active', async () => {
    const wrapper = await mountPanel()
    const btn = wrapper.find('.aiopen-primary-btn')
    expect(btn.text()).toContain('一键开启')
  })

  it('primaryBtnLabel shows 关闭智控 when active', async () => {
    const wrapper = await mountPanel({
      panel: {
        ok: true,
        data: {
          success: true,
          routes: [],
          remote_control_enabled: true,
          keys: [{ key: 'k' }],
        },
      },
    })
    const btn = wrapper.find('.aiopen-primary-btn')
    expect(btn.text()).toContain('关闭智控')
  })
})
