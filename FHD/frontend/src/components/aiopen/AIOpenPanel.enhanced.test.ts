/**
 * AIOpenPanel.vue 增强测试
 * 覆盖：hero 区域、readyStatus、primary action（开启/关闭智控）、
 * client 安装/取消、oneLiner 复制、MCP 工具展示、
 * 远程操控开关、微信开关、OpenClaw、口令创建、
 * 面板加载（成功/失败）、格式化错误、更多设置
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

const mockSafeJsonRequest = vi.fn().mockResolvedValue({ ok: true, data: { success: true }, status: 200 })
const mockGetApiBase = vi.fn(() => 'http://localhost:5100')
const mockBuildAiopenOneLiner = vi.fn(() => 'one-liner-text')
const mockBuildAiAssistantSetupPrompt = vi.fn(() => 'assistant-prompt')
const mockBuildAiopenClientInstalls = vi.fn(() => [
  { id: 'cursor', name: 'Cursor', icon: '🎯', installLabel: '安装', installMode: 'copy', configPath: '~/.cursor/mcp.json', mcpJson: '{"mcpServers":{}}', hint: '配置 MCP' },
  { id: 'claude', name: 'Claude', icon: '🤖', installLabel: '安装', installMode: 'copy', configPath: '~/.claude/config.json', mcpJson: '{"mcpServers":{}}', hint: '配置 MCP' },
])
const mockMarkAiopenClientInstalled = vi.fn()
const mockUnmarkAiopenClientInstalled = vi.fn()
const mockReadAiopenInstalledClients = vi.fn(() => [])
const mockResolveAiopenBackendBase = vi.fn((origin: string) => origin)

vi.mock('@/utils/safeJsonRequest', () => ({
  safeJsonRequest: (...args: unknown[]) => mockSafeJsonRequest(...args),
}))

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => mockGetApiBase(),
  DEFAULT_MOD_API_TIMEOUT_MS: 30000,
}))

vi.mock('@/composables/useAiOpenCursor', () => ({
  useAiOpenCursor: () => ({
    enabled: { value: false },
    connected: { value: false },
    setEnabled: vi.fn(),
  }),
}))

vi.mock('@/utils/aiopenMcpInstall', () => ({
  AIOPEN_MCP_SERVER_NAME: 'AIOPEN',
  buildAiopenClientInstalls: (...args: unknown[]) => mockBuildAiopenClientInstalls(...args),
  buildAiAssistantSetupPrompt: (...args: unknown[]) => mockBuildAiAssistantSetupPrompt(...args),
  buildAiopenOneLiner: (...args: unknown[]) => mockBuildAiopenOneLiner(...args),
  markAiopenClientInstalled: (...args: unknown[]) => mockMarkAiopenClientInstalled(...args),
  unmarkAiopenClientInstalled: (...args: unknown[]) => mockUnmarkAiopenClientInstalled(...args),
  readAiopenInstalledClients: (...args: unknown[]) => mockReadAiopenInstalledClients(...args),
  resolveAiopenBackendBase: (...args: unknown[]) => mockResolveAiopenBackendBase(...args),
}))

// Mock clipboard
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
  writable: true,
})

async function mountAIOpenPanel() {
  const AIOpenPanel = (await import('./AIOpenPanel.vue')).default
  const wrapper = mount(AIOpenPanel, {
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await vi.dynamicImportSettled()
  return wrapper
}

describe('AIOpenPanel.vue – component structure', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: 'http://localhost:28789', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('renders AIOPEN shell', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-shell').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders hero section with AIOPEN title', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-hero').exists()).toBe(true)
    expect(wrapper.text()).toContain('AIOPEN')
    wrapper.unmount()
  })

  it('renders feature intro list', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-features').exists()).toBe(true)
    const features = wrapper.findAll('.aiopen-features li')
    expect(features.length).toBe(3)
    wrapper.unmount()
  })

  it('renders flow steps', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-flow').exists()).toBe(true)
    const steps = wrapper.findAll('.aiopen-flow-item')
    expect(steps.length).toBe(3)
    wrapper.unmount()
  })

  it('renders primary action button', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-primary-btn').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders one-liner section', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-oneline').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders client grid', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-client-grid').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders more settings details', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.find('.aiopen-more').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – readyStatus computed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('readyStatus is off when nothing enabled', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.readyStatus).toBe('off')
    wrapper.unmount()
  })

  it('readyStatus is off initially', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.readyStatus).toBe('off')
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – primary action button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('shows "一键开启" when not active', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.primaryBtnLabel).toBe('一键开启')
    wrapper.unmount()
  })

  it('shows "关闭智控" when active', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.remoteControlEnabled = true
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.primaryBtnLabel).toBe('关闭智控')
    wrapper.unmount()
  })

  it('calls quickSetup on primary action when not active', async () => {
    const wrapper = await mountAIOpenPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true }, status: 200 })
    await wrapper.vm.handlePrimaryAction()
    expect(wrapper.vm.setupRunning).toBe(false)
    wrapper.unmount()
  })

  it('calls shutdownAiOpen on primary action when active', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.remoteControlEnabled = true
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true }, status: 200 })
    await wrapper.vm.handlePrimaryAction()
    expect(wrapper.vm.shutdownRunning).toBe(false)
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – client handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    mockReadAiopenInstalledClients.mockReturnValue([])
  })

  it('renders AI client buttons', async () => {
    const wrapper = await mountAIOpenPanel()
    const clientBtns = wrapper.findAll('.aiopen-client-btn')
    expect(clientBtns.length).toBe(2)
    wrapper.unmount()
  })

  it('shows install label for uninstalled client', async () => {
    const wrapper = await mountAIOpenPanel()
    const label = wrapper.vm.clientActionLabel({ id: 'cursor', installLabel: '安装' })
    expect(label).toBe('安装')
    wrapper.unmount()
  })

  it('shows cancel label for installed client', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.installedClientIds = ['cursor']
    const label = wrapper.vm.clientActionLabel({ id: 'cursor', installLabel: '安装' })
    expect(label).toBe('再次点击取消')
    wrapper.unmount()
  })

  it('resets client selection on click when installed', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.installedClientIds = ['cursor']
    await wrapper.vm.handleClientClick({ id: 'cursor', name: 'Cursor' })
    expect(mockUnmarkAiopenClientInstalled).toHaveBeenCalledWith('cursor')
    wrapper.unmount()
  })

  it('installs client on click when not installed', async () => {
    const wrapper = await mountAIOpenPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, key: 'test-key' }, status: 200 })
    await wrapper.vm.handleClientClick({ id: 'claude', name: 'Claude', installMode: 'copy', mcpJson: '{}' })
    expect(mockMarkAiopenClientInstalled).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – copy functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('copyOneLiner copies text and marks as installed', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.newKey = 'test-key'
    await wrapper.vm.copyOneLiner()
    expect(navigator.clipboard.writeText).toHaveBeenCalled()
    expect(wrapper.vm.oneLinerCopied).toBe(true)
    wrapper.unmount()
  })

  it('copyAiAssistantPrompt copies prompt', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.newKey = 'test-key'
    await wrapper.vm.copyAiAssistantPrompt()
    expect(navigator.clipboard.writeText).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('copyText sets accessResult on success', async () => {
    const wrapper = await mountAIOpenPanel()
    await wrapper.vm.copyText('test')
    expect(wrapper.vm.accessResult).toBe('已复制')
    wrapper.unmount()
  })

  it('copyText sets error message on failure', async () => {
    const wrapper = await mountAIOpenPanel()
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error('fail'))
    await wrapper.vm.copyText('test')
    expect(wrapper.vm.accessResult).toBe('复制失败，请手动复制')
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – panel loading', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads panel data on mount', async () => {
    mockSafeJsonRequest.mockResolvedValue({
      ok: true,
      data: {
        success: true,
        wechat_open: true,
        routes: [{ path: '/api/test', enabled: true }],
        openclaw_base: 'http://localhost:28789',
        remote_control_enabled: true,
        keys: [{ id: 1 }],
      },
      status: 200,
    })
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.wechatOpen).toBe(true)
    expect(wrapper.vm.remoteControlEnabled).toBe(true)
    expect(wrapper.vm.routes.length).toBe(1)
    wrapper.unmount()
  })

  it('handles panel load failure gracefully', async () => {
    mockSafeJsonRequest.mockResolvedValue({ ok: false, status: 500, message: 'Server error' })
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.panelAvailable).toBe(false)
    expect(wrapper.vm.panelError).toBeTruthy()
    wrapper.unmount()
  })

  it('handles panel load network error', async () => {
    mockSafeJsonRequest.mockRejectedValue(new Error('Network error'))
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.panelAvailable).toBe(false)
    expect(wrapper.vm.panelError).toBeTruthy()
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – formatPanelError', () => {
  it('formats 404 error', async () => {
    const wrapper = await mountAIOpenPanel()
    const result = wrapper.vm.formatPanelError({ status: 404 })
    expect(result).toContain('后端未就绪')
    wrapper.unmount()
  })

  it('formats 502 error', async () => {
    const wrapper = await mountAIOpenPanel()
    const result = wrapper.vm.formatPanelError({ status: 502 })
    expect(result).toContain('后端未启动')
    wrapper.unmount()
  })

  it('formats 500 error', async () => {
    const wrapper = await mountAIOpenPanel()
    const result = wrapper.vm.formatPanelError({ status: 500 })
    expect(result).toContain('后端未启动')
    wrapper.unmount()
  })

  it('formats non-JSON error', async () => {
    const wrapper = await mountAIOpenPanel()
    const result = wrapper.vm.formatPanelError({ message: '未返回JSON' })
    expect(result).toContain('后端未启动')
    wrapper.unmount()
  })

  it('formats generic error', async () => {
    const wrapper = await mountAIOpenPanel()
    const result = wrapper.vm.formatPanelError({ message: '自定义错误' })
    expect(result).toBe('自定义错误')
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – createKey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('creates key successfully', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/keys')) {
        return Promise.resolve({ ok: true, data: { success: true, key: 'new-api-key' }, status: 200 })
      }
      return Promise.resolve({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await wrapper.vm.createKey()
    expect(wrapper.vm.newKey).toBe('new-api-key')
    wrapper.unmount()
  })

  it('handles key creation failure', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/keys')) {
        return Promise.resolve({ ok: false, message: '生成失败' })
      }
      return Promise.resolve({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await wrapper.vm.createKey()
    expect(wrapper.vm.accessResult).toBe('生成失败')
    wrapper.unmount()
  })

  it('skips key creation when panel not available', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = false
    await wrapper.vm.createKey()
    expect(wrapper.vm.accessResult).toContain('开发模式')
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – toggle controls', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true }, status: 200 })
  })

  it('toggleRemoteControl updates state', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = true
    await wrapper.vm.toggleRemoteControl({ target: { checked: true } })
    expect(wrapper.vm.remoteControlEnabled).toBe(true)
    wrapper.unmount()
  })

  it('toggleWechat updates state', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = true
    await wrapper.vm.toggleWechat({ target: { checked: true } })
    expect(wrapper.vm.wechatOpen).toBe(true)
    wrapper.unmount()
  })

  it('toggleWhitelist updates route state', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = true
    wrapper.vm.routes = [{ path: '/api/test', enabled: false }]
    await wrapper.vm.toggleWhitelist('/api/test', { target: { checked: true } })
    expect(wrapper.vm.routes[0].enabled).toBe(true)
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – OpenClaw', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('saveOpenclawBase saves when panel available', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = true
    wrapper.vm.openclawBase = 'http://new-host:28789'
    mockSafeJsonRequest.mockResolvedValue({ ok: true })
    await wrapper.vm.saveOpenclawBase()
    expect(wrapper.vm.openclawResult).toBe('已保存')
    wrapper.unmount()
  })

  it('saveOpenclawBase skips when panel not available', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.panelAvailable = false
    await wrapper.vm.saveOpenclawBase()
    expect(mockSafeJsonRequest).not.toHaveBeenCalledWith(expect.stringContaining('/api/aiopen/config'), expect.anything())
    wrapper.unmount()
  })

  it('sendToOpenclaw sends message', async () => {
    const wrapper = await mountAIOpenPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true } })
    wrapper.vm.openclawMessage = '测试消息'
    await wrapper.vm.sendToOpenclaw()
    expect(wrapper.vm.openclawResult).toBe('发送成功')
    wrapper.unmount()
  })

  it('sendToOpenclaw handles failure', async () => {
    const wrapper = await mountAIOpenPanel()
    mockSafeJsonRequest.mockResolvedValue({ ok: false, message: '发送失败' })
    await wrapper.vm.sendToOpenclaw()
    expect(wrapper.vm.openclawResult).toBe('发送失败')
    wrapper.unmount()
  })

  it('sendToOpenclaw handles network error', async () => {
    const wrapper = await mountAIOpenPanel()
    mockSafeJsonRequest.mockRejectedValue(new Error('Network error'))
    await wrapper.vm.sendToOpenclaw()
    expect(wrapper.vm.openclawResult).toBe('Network error')
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – computed properties', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('mcpUrl is computed from backendOrigin', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.mcpUrl).toContain('/api/aiopen/mcp')
    wrapper.unmount()
  })

  it('guideUrl is computed from backendOrigin', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.guideUrl).toContain('/api/aiopen/guide')
    wrapper.unmount()
  })

  it('oneLinerPreview truncates long text', async () => {
    mockBuildAiopenOneLiner.mockReturnValue('a'.repeat(80))
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.oneLinerPreview.length).toBeLessThanOrEqual(75) // 72 + '…'
    wrapper.unmount()
  })

  it('oneLinerPreview keeps short text as-is', async () => {
    mockBuildAiopenOneLiner.mockReturnValue('short text')
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.oneLinerPreview).toBe('short text')
    wrapper.unmount()
  })

  it('aiOpenActive is true when remoteControlEnabled', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.remoteControlEnabled = true
    expect(wrapper.vm.aiOpenActive).toBe(true)
    wrapper.unmount()
  })

  it('hasConnectConfig is true when activeKey exists', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.newKey = 'test-key'
    expect(wrapper.vm.hasConnectConfig).toBe(true)
    wrapper.unmount()
  })

  it('hasConnectConfig is true when keys exist', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.keys = [{ id: 1 }]
    expect(wrapper.vm.hasConnectConfig).toBe(true)
    wrapper.unmount()
  })

  it('selectedClient returns matching client', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.selectedClientId = 'cursor'
    expect(wrapper.vm.selectedClient.id).toBe('cursor')
    wrapper.unmount()
  })

  it('selectedClientConfigSnippet returns mcpJson', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.selectedClientId = 'cursor'
    expect(typeof wrapper.vm.selectedClientConfigSnippet).toBe('string')
    wrapper.unmount()
  })

  it('friendlyTools maps manifestTools with labels', async () => {
    const wrapper = await mountAIOpenPanel()
    wrapper.vm.manifestTools = [{ name: 'api_call', description: '调用接口' }, { name: 'unknown_tool', description: '未知工具' }]
    const tools = wrapper.vm.friendlyTools
    expect(tools[0].label).toBe('调用接口')
    expect(tools[1].label).toBe('unknown_tool')
    wrapper.unmount()
  })

  it('flowDone tracks completion state', async () => {
    const wrapper = await mountAIOpenPanel()
    expect(wrapper.vm.flowDone).toEqual([false, false, false])
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – back emit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSafeJsonRequest.mockResolvedValue({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
  })

  it('emits back on header click', async () => {
    const wrapper = await mountAIOpenPanel()
    await wrapper.find('.aiopen-back').trigger('click')
    expect(wrapper.emitted('back')).toBeTruthy()
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – MCP health probe', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sets mcpHealthy when manifest is valid', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/manifest')) {
        return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [{ name: 'api_call' }] }, status: 200 })
      }
      return Promise.resolve({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await vi.waitFor(() => expect(wrapper.vm.mcpHealthy).toBe(true), { timeout: 3000 })
    expect(wrapper.vm.mcpHealthText).toContain('MCP 服务正常')
    wrapper.unmount()
  })

  it('sets mcpHealthy via mcp probe when manifest fails', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/manifest')) {
        return Promise.resolve({ ok: false, status: 404 })
      }
      if (url.includes('/mcp')) {
        return Promise.resolve({ ok: true, data: { success: true, server: 'AIOPEN', tool_count: 5 }, status: 200 })
      }
      return Promise.resolve({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await vi.waitFor(() => expect(wrapper.vm.mcpHealthy).toBe(true), { timeout: 3000 })
    wrapper.unmount()
  })

  it('handles 403 on MCP probe', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/manifest') || url.includes('/mcp')) {
        return Promise.resolve({ ok: false, status: 403 })
      }
      return Promise.resolve({ ok: true, data: { success: true, wechat_open: false, routes: [], openclaw_base: '', remote_control_enabled: false, keys: [] }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await vi.waitFor(() => expect(wrapper.vm.mcpHealthText).toContain('403'), { timeout: 3000 })
    wrapper.unmount()
  })
})

describe('AIOpenPanel.vue – loadPanel refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loadPanel refreshes all data', async () => {
    mockSafeJsonRequest.mockImplementation((url: string) => {
      if (url.includes('/panel')) {
        return Promise.resolve({ ok: true, data: { success: true, wechat_open: true, routes: [], openclaw_base: '', remote_control_enabled: true, keys: [] }, status: 200 })
      }
      if (url.includes('/manifest')) {
        return Promise.resolve({ ok: true, data: { success: true, name: 'AIOPEN', tools: [] }, status: 200 })
      }
      if (url.includes('/install')) {
        return Promise.resolve({ ok: true, data: { success: true }, status: 200 })
      }
      return Promise.resolve({ ok: true, data: { success: true }, status: 200 })
    })
    const wrapper = await mountAIOpenPanel()
    await wrapper.vm.loadPanel()
    expect(wrapper.vm.wechatOpen).toBe(true)
    expect(wrapper.vm.remoteControlEnabled).toBe(true)
    wrapper.unmount()
  })
})
