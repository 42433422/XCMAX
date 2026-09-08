import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { checkScreenControl, controlState, pressScreenKey, screenRoutes, selectScreenOption } from './aiopenScreenControls'
import { initAiOpenCursor, setAiOpenCursorEnabled, aiopenCursorLogs } from './useAiOpenCursor'

vi.mock('@/utils/apiBase', () => ({ getApiBase: () => 'http://127.0.0.1:5000' }))

function mountInput(properties: Partial<HTMLInputElement>) {
  const input = Object.assign(document.createElement('input'), properties)
  document.body.appendChild(input)
  return input
}

function mountSelect(multiple = false) {
  const select = document.createElement('select')
  select.multiple = multiple
  select.append(new Option('A', 'a', true, true), new Option('B', 'b'))
  document.body.appendChild(select)
  return select
}

describe('semantic screen controls', () => {
  afterEach(() => { document.body.replaceChildren() })

  it('updates a native select and dispatches change once', async () => {
    const select = mountSelect()
    const changed = vi.fn()
    select.addEventListener('change', changed)
    expect(await selectScreenOption(select, { values: ['b'] })).toEqual({ success: true, selected: ['b'] })
    expect(select.value).toBe('b')
    expect(changed).toHaveBeenCalledTimes(1)
    expect(controlState(select).options).toEqual([
      { value: 'a', label: 'A', selected: false, disabled: false },
      { value: 'b', label: 'B', selected: true, disabled: false },
    ])
  })

  it('rejects missing or disabled options without partially changing the selection', async () => {
    const select = mountSelect(true)
    select.options[1]!.disabled = true
    expect((await selectScreenOption(select, { values: ['a', 'b'] })).success).toBe(false)
    expect((await selectScreenOption(select, { values: ['missing'] })).success).toBe(false)
    expect(select.value).toBe('a')
  })

  it('sets checkbox state idempotently using the native click behavior', async () => {
    const checkbox = mountInput({ type: 'checkbox' })
    const changed = vi.fn()
    checkbox.addEventListener('change', changed)
    expect(await checkScreenControl(checkbox, { checked: true })).toEqual({ success: true, checked: true })
    expect(await checkScreenControl(checkbox, { checked: true })).toEqual({ success: true, checked: true })
    expect(changed).toHaveBeenCalledTimes(1)
    expect(await checkScreenControl(checkbox, { checked: false })).toEqual({ success: true, checked: false })
    expect(changed).toHaveBeenCalledTimes(2)
  })

  it('detects a controlled checkbox rejecting the requested change', async () => {
    const checkbox = mountInput({ type: 'checkbox' })
    checkbox.addEventListener('click', (event) => event.preventDefault())
    expect((await checkScreenControl(checkbox, { checked: true })).success).toBe(false)
  })

  it('rejects disabled and read-only controls', async () => {
    mountInput({ type: 'checkbox', disabled: true })
    mountInput({ readOnly: true })
    await expect(checkScreenControl(document.querySelector('input')!, { checked: true })).rejects.toThrow('禁用')
    await expect(pressScreenKey(document.querySelector('input[readonly]')!, { key: 'Enter' })).rejects.toThrow('只读')
  })

  it('dispatches keyboard commands to actual application handlers', async () => {
    const button = document.createElement('button')
    document.body.appendChild(button)
    const click = vi.fn()
    button.addEventListener('click', click)
    expect((await pressScreenKey(button, { key: 'Enter' })).success).toBe(true)
    expect(click).toHaveBeenCalledTimes(1)
    button.addEventListener('keydown', (event) => event.preventDefault())
    await pressScreenKey(button, { key: 'Enter' })
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('discovers a Mod route added after initial startup', () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: {} }] })
    router.addRoute({ path: '/mods/new-workspace', name: 'dynamic-mod', component: {}, meta: { title: '新增工作区' } })
    const catalog = screenRoutes(router)
    expect(catalog.routes).toContainEqual({ path: '/mods/new-workspace', name: 'dynamic-mod', title: '新增工作区', parameterized: false, redirect: false })
  })
})

describe('screen transport contracts', () => {
  let requestId = 0
  let sockets: Array<{ onmessage: ((event: { data: string }) => Promise<void>) | null; send: ReturnType<typeof vi.fn> }>

  beforeEach(() => {
    sockets = []
    vi.useFakeTimers()
    localStorage.clear()
    vi.stubGlobal('CSS', { escape: (value: string) => value })
    vi.stubGlobal('WebSocket', class {
      onmessage = null
      send = vi.fn()
      close = vi.fn()
      constructor() { sockets.push(this) }
    })
    initAiOpenCursor(createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: {} }] }))
    setAiOpenCursorEnabled(true)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 100, height: 30, x: 0, y: 0, top: 0, bottom: 30 } as DOMRect)
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() })
  })

  afterEach(() => {
    setAiOpenCursorEnabled(false)
    document.body.replaceChildren()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  async function command(action: string, params: Record<string, unknown> = {}) {
    const socket = sockets[sockets.length - 1]!
    const task = socket.onmessage!({ data: JSON.stringify({ type: 'command', id: `test-${++requestId}`, action, params }) })
    await vi.runAllTimersAsync()
    await task
    return JSON.parse(socket.send.mock.lastCall![0]).result
  }

  it('paginates every visible control instead of silently truncating after 120', async () => {
    for (let i = 0; i < 125; i++) {
      const button = document.createElement('button')
      button.id = `button-${i}`
      document.body.appendChild(button)
    }
    const first = await command('snapshot')
    expect(first.total_elements).toBe(125)
    expect(first.next_offset).toBe(120)
    const second = await command('snapshot', { offset: first.next_offset })
    expect(second.elements).toHaveLength(5)
    expect(second.next_offset).toBeNull()
  })

  it('does not return or log password values on read or type', async () => {
    mountInput({ id: 'password', type: 'password', value: 'old-secret' })
    expect(JSON.stringify(await command('snapshot'))).not.toContain('old-secret')
    const typed = await command('type', { selector: '#password', text: 'new-secret' })
    expect(typed.success).toBe(true)
    expect(document.querySelector<HTMLInputElement>('input')!.value).toBe('new-secret')
    expect(JSON.stringify(typed)).not.toContain('new-secret')
    expect(aiopenCursorLogs.value.join('\n')).not.toContain('new-secret')
  })

  it('rejects stale page commands before touching a control', async () => {
    mountInput({ id: 'field', value: 'unchanged' })
    const result = await command('type', { selector: '#field', text: 'changed', expected_route: '/other' })
    expect(result.code).toBe('STALE_SCREEN')
    expect(document.querySelector<HTMLInputElement>('input')!.value).toBe('unchanged')
  })

  it('rejects ambiguous selectors without clicking either target', async () => {
    for (const text of ['A', 'B']) {
      const button = document.createElement('button')
      button.textContent = text
      document.body.appendChild(button)
    }
    const clicked = vi.fn()
    document.querySelectorAll('button').forEach((button) => button.addEventListener('click', clicked))
    expect((await command('click', { selector: 'button' })).success).toBe(false)
    expect(clicked).not.toHaveBeenCalled()
  })
})
