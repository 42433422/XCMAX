import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  requestAction: vi.fn(),
  setMode: vi.fn(),
  detectTarget: vi.fn(),
  start: vi.fn(),
  serializeVisibleDom: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('./usePrivacyManager', () => ({
  usePrivacyManager: () => ({ requestAction: mocks.requestAction }),
}))

vi.mock('../../stores/agent', () => ({
  useAgentStore: () => ({ setMode: mocks.setMode }),
}))

vi.mock('./useButlerOrchestrator', () => ({
  useButlerOrchestrator: () => ({
    detectTarget: mocks.detectTarget,
    start: mocks.start,
  }),
}))

vi.mock('../../utils/agent/pageSerializer', () => ({
  serializeVisibleDom: mocks.serializeVisibleDom,
}))

import { getActionLog, useActionExecutor } from './useActionExecutor'

describe('useActionExecutor', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    sessionStorage.clear()
    vi.restoreAllMocks()
    vi.clearAllMocks()
    mocks.push.mockResolvedValue(undefined)
    mocks.requestAction.mockResolvedValue(true)
    mocks.detectTarget.mockReturnValue({ type: 'mod', id: 'demo-mod' })
    mocks.start.mockResolvedValue({ ok: true })
    mocks.serializeVisibleDom.mockReturnValue('visible dom content')
    Object.defineProperty(window, 'scrollTo', { configurable: true, value: vi.fn() })
    Object.defineProperty(window, 'scrollBy', { configurable: true, value: vi.fn() })
    Object.defineProperty(document.body, 'scrollHeight', { configurable: true, value: 1280 })
  })

  it('records bounded navigation logs and tolerates broken session storage data', async () => {
    const api = useActionExecutor()

    sessionStorage.setItem('xc_butler_action_log', '{bad json')
    expect(getActionLog()).toEqual([])
    sessionStorage.clear()

    for (let i = 0; i < 55; i += 1) {
      await api.navigate({ name: `Route${i}`, query: { page: String(i) } })
    }

    const entries = getActionLog()
    expect(entries).toHaveLength(50)
    expect(entries[0].label).toBe('跳转到 Route5')
    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'Route54', query: { page: '54' } })

    mocks.push.mockRejectedValueOnce(new Error('route boom'))
    await expect(api.navigate({ route: 'missing-route' })).resolves.toMatchObject({
      success: false,
      message: 'route boom',
    })

    const storageProto = Object.getPrototypeOf(window.sessionStorage)
    vi.spyOn(storageProto, 'getItem').mockImplementationOnce(() => {
      throw new Error('blocked')
    })
    await expect(api.navigate({ route: 'fallback-route' })).resolves.toMatchObject({ success: true })
  })

  it('clicks by every supported target strategy and reports cancel, missing, invalid, and thrown clicks', async () => {
    const api = useActionExecutor()

    mocks.requestAction.mockResolvedValueOnce(false)
    await expect(api.click({ selector: '.never', label: '取消按钮' })).resolves.toMatchObject({
      success: false,
      message: '用户已取消',
    })

    await expect(api.click({ selector: '[', label: '坏选择器' })).resolves.toMatchObject({
      success: false,
      message: '未找到目标元素：坏选择器',
    })

    await expect(api.click({ butlerTarget: 'missing-target' })).resolves.toMatchObject({
      success: false,
      message: '未找到目标元素：missing-target',
    })

    const directButton = document.createElement('button')
    directButton.className = 'direct'
    directButton.click = vi.fn()
    document.body.appendChild(directButton)
    await expect(api.click({ selector: '.direct', label: '直接按钮' })).resolves.toMatchObject({
      success: true,
    })

    const dataButton = document.createElement('button')
    dataButton.dataset.butlerId = 'primary-action'
    dataButton.click = vi.fn()
    document.body.appendChild(dataButton)
    await expect(api.click({ butlerTarget: 'primary-action' })).resolves.toMatchObject({
      success: true,
    })

    const ariaButton = document.createElement('button')
    ariaButton.setAttribute('aria-label', '保存设置')
    ariaButton.click = vi.fn()
    document.body.appendChild(ariaButton)
    await expect(api.click({ label: '保存设置' })).resolves.toMatchObject({ success: true })

    const textButton = document.createElement('button')
    textButton.textContent = '确认提交'
    textButton.click = vi.fn(() => {
      throw new Error('click boom')
    })
    document.body.appendChild(textButton)
    await expect(api.click({ label: '提交' })).resolves.toMatchObject({
      success: false,
      message: 'click boom',
    })
  })

  it('fills fields through native setters, fallback value assignment, and error handling', async () => {
    const api = useActionExecutor()

    mocks.requestAction.mockResolvedValueOnce(false)
    await expect(api.fill({ selector: '.field', label: '姓名', value: '取消' })).resolves.toMatchObject({
      success: false,
      message: '用户已取消',
    })

    await expect(api.fill({ selector: '.missing', label: '姓名', value: '张三' })).resolves.toMatchObject({
      success: false,
      message: '未找到输入框：姓名',
    })

    const input = document.createElement('input')
    input.className = 'field'
    const events: string[] = []
    input.addEventListener('input', () => events.push('input'))
    input.addEventListener('change', () => events.push('change'))
    document.body.appendChild(input)
    await expect(api.fill({ selector: '.field', label: '姓名', value: '张三' })).resolves.toMatchObject({
      success: true,
    })
    expect(input.value).toBe('张三')
    expect(events).toEqual(['input', 'change'])

    const fallback = document.createElement('div') as HTMLDivElement & { value?: string }
    fallback.dataset.butlerId = 'pseudo-input'
    document.body.appendChild(fallback)
    await expect(api.fill({ butlerTarget: 'pseudo-input', value: 'fallback' })).resolves.toMatchObject({
      success: true,
    })
    expect(fallback.value).toBe('fallback')

    const broken = document.createElement('input')
    broken.className = 'broken-field'
    const proto = Object.create(HTMLInputElement.prototype)
    Object.defineProperty(proto, 'value', {
      configurable: true,
      set() {
        throw new Error('fill boom')
      },
    })
    Object.setPrototypeOf(broken, proto)
    document.body.appendChild(broken)
    await expect(api.fill({ selector: '.broken-field', label: '坏输入', value: 'x' })).resolves.toMatchObject({
      success: false,
      message: 'fill boom',
    })
  })

  it('selects options and reports cancel, missing, and dispatch failures', async () => {
    const api = useActionExecutor()

    mocks.requestAction.mockResolvedValueOnce(false)
    await expect(api.select({ selector: '.tier', label: '套餐', value: 'pro' })).resolves.toMatchObject({
      success: false,
      message: '用户已取消',
    })

    await expect(api.select({ selector: '.missing-tier', label: '套餐', value: 'pro' })).resolves.toMatchObject({
      success: false,
      message: '未找到选择框：套餐',
    })

    const select = document.createElement('select')
    select.className = 'tier'
    const option = document.createElement('option')
    option.value = 'pro'
    select.appendChild(option)
    const changes: string[] = []
    select.addEventListener('change', () => changes.push(select.value))
    document.body.appendChild(select)

    await expect(api.select({ selector: '.tier', label: '套餐', value: 'pro' })).resolves.toMatchObject({
      success: true,
    })
    expect(changes).toEqual(['pro'])

    const broken = document.createElement('select')
    broken.className = 'broken-tier'
    Object.defineProperty(broken, 'dispatchEvent', {
      configurable: true,
      value: () => {
        throw new Error('select boom')
      },
    })
    document.body.appendChild(broken)
    await expect(api.select({ selector: '.broken-tier', label: '坏套餐', value: 'team' })).resolves.toMatchObject({
      success: false,
      message: 'select boom',
    })
  })

  it('scrolls all directions and reads serialized page content', async () => {
    const api = useActionExecutor()

    await expect(api.scroll({ direction: 'top' })).resolves.toMatchObject({ message: '已滚动：top' })
    await expect(api.scroll({ direction: 'bottom' })).resolves.toMatchObject({ message: '已滚动：bottom' })
    await expect(api.scroll({ direction: 'up', px: 120 })).resolves.toMatchObject({ message: '已滚动：up' })
    await expect(api.scroll({ direction: 'down', px: 90 })).resolves.toMatchObject({ message: '已滚动：down' })

    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' })
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 1280, behavior: 'smooth' })
    expect(window.scrollBy).toHaveBeenCalledWith({ top: -120, behavior: 'smooth' })
    expect(window.scrollBy).toHaveBeenCalledWith({ top: 90, behavior: 'smooth' })

    await expect(api.read()).resolves.toMatchObject({
      success: true,
      message: 'visible dom content',
      assistantReply: '当前页面内容摘要：\nvisible dom content',
    })
  })

  it('runs enhance-current-page cancel, unsupported page, failure, and success paths', async () => {
    const api = useActionExecutor()

    mocks.requestAction.mockResolvedValueOnce(false)
    await expect(api.enhanceCurrentPage({ brief: '改成 CRM' })).resolves.toMatchObject({
      success: false,
      message: '用户已取消',
      assistantReply: '已取消，未做任何修改。',
    })

    mocks.detectTarget.mockReturnValueOnce(null)
    await expect(api.enhanceCurrentPage({ brief: '改成 CRM' })).resolves.toMatchObject({
      success: false,
      message: '当前页面无法直接改写',
    })

    mocks.start.mockResolvedValueOnce({ ok: false, error: 'pipeline down' })
    await expect(api.enhanceCurrentPage({ brief: '增强表单', scope: 'page' })).resolves.toMatchObject({
      success: false,
      message: 'pipeline down',
      assistantReply: '改写启动失败：pipeline down',
    })

    await expect(api.enhanceCurrentPage({ brief: '增强表单', scope: 'page' })).resolves.toMatchObject({
      success: true,
      message: '改写管线已启动',
    })
    expect(mocks.start).toHaveBeenLastCalledWith('增强表单', 'page')
  })
})
