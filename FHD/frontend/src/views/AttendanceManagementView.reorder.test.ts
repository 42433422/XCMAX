import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import AttendanceManagementView from '../../../XCAGI/mods/attendance-industry/frontend/views/AttendanceManagementView.vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const apiFetch = vi.fn()
const appConfirm = vi.fn()
vi.mock('@/utils/apiBase', () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: (...args: unknown[]) => appConfirm(...args) }))

type Person = { id: number; employee_name: string; order_position: number }
const people: Person[] = [
  { id: 26, employee_name: 'First', order_position: 26 },
  { id: 40, employee_name: 'Middle', order_position: 38 },
  { id: 60, employee_name: 'Last', order_position: 90 },
]
function response(data: unknown, ok = true, message = '') {
  return { ok, status: ok ? 200 : 409, json: async () => ({ success: ok, data, message }) }
}
function bounds(top: number, height: number, width = 800): DOMRect {
  return { top, bottom: top + height, left: 0, right: width, width, height, x: 0, y: top, toJSON: () => ({}) }
}
function pointer(target: EventTarget, type: string, values: Record<string, unknown> = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.assign(event, { pointerId: 7, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: 200, clientY: 120, ...values })
  target.dispatchEvent(event)
  return event
}
function touch(target: EventTarget, type: string, y = 120) {
  const point = { identifier: 9, clientX: 200, clientY: y, target }
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.assign(event, { touches: /end|cancel/.test(type) ? [] : [point], changedTouches: [point] })
  target.dispatchEvent(event)
  return event
}

let wrapper: VueWrapper
function renderedIds() {
  return wrapper.findAll('tbody tr[data-roster-id]').map(row => Number(row.attributes('data-roster-id')))
}
function writes() {
  return apiFetch.mock.calls.filter(([, init]) => init?.method === 'POST')
}
async function settle() { await nextTick(); await flushPromises(); await nextTick() }
async function mountRoster(items = people, total = 80) {
  apiFetch.mockImplementation((url: string) => response(url.includes('/departments?')
    ? { items: [{ department: 'Engineering' }] }
    : { items, total, roster_total: 100, order_revision: 'owner-roster-revision' }))
  wrapper = mount(AttendanceManagementView, {
    props: { section: 'personnel' }, attachTo: document.body,
    global: { stubs: { TransitionGroup: false, RouterLink: { template: '<a><slot /></a>' } } },
  })
  await settle()
}
async function hold(pointerType = 'mouse') {
  pointer(wrapper.get('tbody tr[data-roster-id]').element, 'pointerdown', { pointerType })
  await vi.advanceTimersByTimeAsync(500)
  await nextTick()
}
async function move(y = 200) {
  pointer(document, 'pointermove', { clientY: y })
  await vi.advanceTimersByTimeAsync(32)
  await nextTick()
}
async function drop(y = 200) {
  pointer(document, 'pointerup', { clientY: y })
  await settle()
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame'] })
  apiFetch.mockReset()
  appConfirm.mockReset().mockResolvedValue(true)
  productReadAccountEpoch.value = 0
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.matches('tr[data-roster-id]')) {
      const rows = Array.from(this.parentElement?.querySelectorAll(':scope > tr[data-roster-id]') || [])
      const scroll = this.closest('.table-scroll')?.scrollTop || 0
      return bounds(100 + rows.indexOf(this) * 40 - scroll, 40)
    }
    if (this.matches('tbody')) return bounds(100 - (this.closest('.table-scroll')?.scrollTop || 0), 120)
    if (this.matches('.table-scroll')) return bounds(100, 120)
    return bounds(0, 600)
  })
})
afterEach(() => {
  wrapper?.unmount()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('Attendance personnel long-press reorder', () => {
  it('leaves a short press and normal row click unchanged', async () => {
    await mountRoster()
    pointer(wrapper.get('tbody tr[data-roster-id]').element, 'pointerdown')
    await vi.advanceTimersByTimeAsync(400)
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
    await drop(120)
    await vi.advanceTimersByTimeAsync(600)
    await wrapper.get('tbody .primary-cell').trigger('click')
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(writes()).toEqual([])
  })

  it('requires the complete 500ms hold before lifting a row', async () => {
    await mountRoster()
    pointer(wrapper.get('tbody tr[data-roster-id]').element, 'pointerdown')
    await vi.advanceTimersByTimeAsync(499)
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(true)
    pointer(document, 'pointercancel')
    expect(writes()).toEqual([])
  })

  it.each(['mouse', 'pen'])('previews %s movement and moves one person at the absolute roster position on release', async pointerType => {
    await mountRoster()
    await wrapper.get('.toolbar-card input').setValue('staff')
    await wrapper.get('.toolbar-card button').trigger('click')
    await settle()
    await wrapper.findAll('.pagination button')[1].trigger('click')
    await settle()
    await hold(pointerType)
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(true)
    await move()
    expect(renderedIds()).toEqual([40, 60, 26])
    expect(writes()).toEqual([])
    await drop()
    expect(writes()).toEqual([[
      '/api/mod/attendance-industry/employees/26/move',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ position: 90, revision: 'owner-roster-revision' }) }),
    ]])
    expect(apiFetch.mock.calls.filter(([url]) => url.includes('/employees?')).at(-1)?.[0]).toMatch(/page=2.*search=staff/)
  })

  it('uses the last pointer position even when release precedes the next animation frame', async () => {
    await mountRoster()
    await hold()
    pointer(document, 'pointermove', { clientY: 200 })
    await drop()
    expect(writes()[0]?.[1].body).toBe(JSON.stringify({ position: 90, revision: 'owner-roster-revision' }))
    expect(writes()).toHaveLength(1)
  })

  it('ignores another pointer and cancels when an additional pointer is pressed', async () => {
    await mountRoster()
    await hold()
    pointer(document, 'pointermove', { pointerId: 8, clientY: 200 })
    pointer(document, 'pointerup', { pointerId: 8, clientY: 200 })
    await nextTick()
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(true)
    pointer(document, 'pointerdown', { pointerId: 8, clientY: 200 })
    await drop()
    expect(writes()).toEqual([])
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
  })

  it('scrolls at a long-list edge and stops immediately when canceled', async () => {
    await mountRoster(Array.from({ length: 20 }, (_, index) => ({ id: index + 1, employee_name: `Person ${index}`, order_position: index + 1 })))
    const viewport = wrapper.get('.table-scroll').element
    Object.defineProperties(viewport, { clientHeight: { configurable: true, value: 120 }, scrollHeight: { configurable: true, value: 800 } })
    await hold()
    await move(214)
    await vi.advanceTimersByTimeAsync(100)
    expect(viewport.scrollTop).toBeGreaterThan(0)
    expect(writes()).toEqual([])
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    const stoppedAt = viewport.scrollTop
    await vi.advanceTimersByTimeAsync(100)
    expect(viewport.scrollTop).toBe(stoppedAt)
    expect(writes()).toEqual([])
  })

  it.each(['pointercancel', 'Escape', 'blur', 'outside', 'missing-release', 'lostpointercapture'])('cancels an active preview on %s without writing', async reason => {
    await mountRoster()
    await hold()
    await move()
    expect(renderedIds()).toEqual([40, 60, 26])
    if (reason === 'Escape') document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    else if (reason === 'blur') window.dispatchEvent(new Event('blur'))
    else if (reason === 'outside') pointer(document, 'pointerup', { clientX: 900, clientY: 200 })
    else if (reason === 'missing-release') pointer(document, 'pointermove', { buttons: 0, clientY: 200 })
    else if (reason === 'lostpointercapture') pointer(wrapper.get('.table-scroll').element, 'lostpointercapture')
    else pointer(document, 'pointercancel')
    await settle()
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
    expect(writes()).toEqual([])
  })

  it('captures a non-touch pointer on the stable viewport and releases it when canceled', async () => {
    await mountRoster()
    const viewport = wrapper.get('.table-scroll').element
    const captured = new Set<number>()
    const capture = vi.fn((id: number) => captured.add(id))
    const release = vi.fn((id: number) => captured.delete(id))
    Object.assign(viewport, { setPointerCapture: capture, hasPointerCapture: (id: number) => captured.has(id), releasePointerCapture: release })
    await hold()
    expect(capture).toHaveBeenCalledExactlyOnceWith(7)
    expect(capture.mock.contexts[0]).toBe(viewport)
    await move()
    expect(renderedIds()).toEqual([40, 60, 26])
    expect(captured.has(7)).toBe(true)
    pointer(viewport, 'lostpointercapture')
    await settle()
    expect(release).toHaveBeenCalledExactlyOnceWith(7)
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(document.querySelector('.roster-drag-ghost')).toBeNull()
    expect(writes()).toEqual([])
  })

  it.each(['movement', 'scroll'])('does not activate when %s occurs before the hold completes', async reason => {
    await mountRoster()
    pointer(wrapper.get('tbody tr[data-roster-id]').element, 'pointerdown')
    if (reason === 'movement') pointer(document, 'pointermove', { clientY: 140 })
    else wrapper.get('.table-scroll').element.dispatchEvent(new Event('scroll'))
    await vi.advanceTimersByTimeAsync(600)
    await drop()
    expect(writes()).toEqual([])
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
  })

  it.each(['input', 'button'])('keeps the existing %s control out of the drag gesture', async selector => {
    await mountRoster()
    pointer(wrapper.get(`tbody tr[data-roster-id] ${selector}`).element, 'pointerdown')
    await vi.advanceTimersByTimeAsync(600)
    await move()
    await drop()
    expect(writes()).toEqual([])
    expect(renderedIds()).toEqual([26, 40, 60])
  })

  it('preserves numeric keyboard ordering and the original revision contract', async () => {
    await mountRoster()
    await wrapper.get('tbody input[type="number"]').setValue(4)
    await settle()
    expect(writes()[0]?.[1].body).toBe(JSON.stringify({ position: 4, revision: 'owner-roster-revision' }))
  })

  it('disables numeric edits while a search draft is unapplied and enables saving after the new read', async () => {
    await mountRoster()
    expect(wrapper.get('tbody input[type="number"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('.toolbar-card input').setValue('staff')
    expect(wrapper.get('tbody input[type="number"]').attributes('disabled')).toBeDefined()
    expect(writes()).toEqual([])
    await wrapper.get('.toolbar-card input').trigger('keyup', { key: 'Enter' })
    await settle()
    expect(wrapper.get('tbody input[type="number"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('tbody input[type="number"]').setValue(4)
    await settle()
    expect(writes()[0]?.[1].body).toBe(JSON.stringify({ position: 4, revision: 'owner-roster-revision' }))
    expect(writes()).toHaveLength(1)
  })

  it.each(['search', 'section', 'account', 'editor'])('cancels or prevents dragging when %s context changes', async change => {
    await mountRoster()
    if (change === 'editor') {
      await wrapper.get('tbody button').trigger('click')
      await settle()
      await hold()
    } else {
      await hold()
      await move()
      if (change === 'search') await wrapper.get('.toolbar-card input').setValue('different')
      else if (change === 'account') productReadAccountEpoch.value++
      else await wrapper.setProps({ section: 'departments' })
    }
    await drop()
    expect(writes()).toEqual([])
    expect(wrapper.find('.roster-row-dragging').exists()).toBe(false)
  })

  it('restores the saved list and keeps a visible conflict message after a failed move', async () => {
    await mountRoster()
    const read = apiFetch.getMockImplementation()!
    apiFetch.mockImplementation((url: string, init?: RequestInit) => init?.method === 'POST'
      ? response(null, false, 'Order changed; refresh required') : read(url, init))
    await hold()
    await move()
    await drop()
    expect(writes()).toHaveLength(1)
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(wrapper.get('[role="alert"]').text()).toContain('Order changed; refresh required')
  })

  it('ignores an old move failure after switching sections and prevents a second move while saving', async () => {
    await mountRoster()
    let finishMove: ((value: ReturnType<typeof response>) => void) | undefined
    const read = apiFetch.getMockImplementation()!
    apiFetch.mockImplementation((url: string, init?: RequestInit) => init?.method === 'POST'
      ? new Promise(resolve => { finishMove = resolve }) : read(url, init))
    await hold()
    await move()
    await drop()
    await hold()
    await move()
    await drop()
    expect(writes()).toHaveLength(1)
    await wrapper.setProps({ section: 'departments' })
    await settle()
    const callsAfterSwitch = apiFetch.mock.calls.length
    finishMove!(response(null, false, 'Old roster conflict'))
    await settle()
    expect(apiFetch).toHaveBeenCalledTimes(callsAfterSwitch)
    expect(wrapper.get('tbody').text()).toContain('Engineering')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('disables refresh while moving and reads the final order after an overlapping same-context query', async () => {
    await mountRoster()
    const read = apiFetch.getMockImplementation()!
    let finishMove: ((value: ReturnType<typeof response>) => void) | undefined
    let persisted = false
    apiFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return new Promise(resolve => { finishMove = resolve })
      if (persisted && url.includes('/employees?')) return response({ items: [people[1], people[2], people[0]], total: 80, roster_total: 100, order_revision: 'saved-revision' })
      return read(url, init)
    })
    await hold()
    await move()
    await drop()
    const refresh = wrapper.get('.header-actions button:last-child')
    expect(refresh.attributes('disabled')).toBeDefined()
    const readCount = apiFetch.mock.calls.length
    await refresh.trigger('click')
    expect(apiFetch).toHaveBeenCalledTimes(readCount)
    await wrapper.get('.toolbar-card input').trigger('keyup', { key: 'Enter' })
    await settle()
    expect(apiFetch.mock.calls.length).toBeGreaterThan(readCount)
    expect(renderedIds()).toEqual([26, 40, 60])
    persisted = true
    finishMove!(response({ position: 90 }))
    await settle()
    expect(renderedIds()).toEqual([40, 60, 26])
    expect(refresh.attributes('disabled')).toBeUndefined()
    expect(writes()).toHaveLength(1)
  })

  it('replaces the old account roster and ignores its outstanding move receipt', async () => {
    await mountRoster()
    let finishMove: ((value: ReturnType<typeof response>) => void) | undefined
    apiFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return new Promise(resolve => { finishMove = resolve })
      if (url.includes('/departments?')) return response({ items: [] })
      return response({ items: [{ id: 201, employee_name: 'New account', order_position: 1 }], total: 1, roster_total: 1, order_revision: 'new-owner-revision' })
    })
    await hold()
    await move()
    await drop()
    productReadAccountEpoch.value++
    await settle()
    expect(renderedIds()).toEqual([201])
    const callsAfterSwitch = apiFetch.mock.calls.length
    finishMove!(response(null, false, 'Old account conflict'))
    await settle()
    expect(renderedIds()).toEqual([201])
    expect(wrapper.text()).not.toContain('First')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(apiFetch).toHaveBeenCalledTimes(callsAfterSwitch)
  })

  it('clears account-specific department suggestions and rejects a late prior-account lookup', async () => {
    await mountRoster()
    const read = apiFetch.getMockImplementation()!
    let finishDepartments: ((value: ReturnType<typeof response>) => void) | undefined
    apiFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (!url.includes('/departments?')) return read(url, init)
      return productReadAccountEpoch.value === 0
        ? new Promise(resolve => { finishDepartments = resolve }) : response({ items: [] })
    })
    await wrapper.get('.header-actions button:last-child').trigger('click')
    await settle()
    expect(wrapper.findAll('datalist option').map(option => option.attributes('value'))).toEqual(['Engineering'])
    productReadAccountEpoch.value++
    await settle()
    expect(wrapper.findAll('datalist option')).toHaveLength(0)
    finishDepartments!(response({ items: [{ department: 'Private old department' }] }))
    await settle()
    expect(wrapper.findAll('datalist option')).toHaveLength(0)
  })

  it.each([true, false])('ignores an old editor receipt after A to B to A, including success=%s', async success => {
    await mountRoster()
    const read = apiFetch.getMockImplementation()!
    let finishSave: ((value: ReturnType<typeof response>) => void) | undefined
    apiFetch.mockImplementation((url: string, init?: RequestInit) => init?.method === 'PUT'
      ? new Promise(resolve => { finishSave = resolve }) : read(url, init))
    await wrapper.get('tbody button').trigger('click')
    await settle()
    await wrapper.get('.editor-actions .btn-primary').trigger('click')
    await settle()
    productReadAccountEpoch.value++
    await settle()
    expect(wrapper.get('dialog').attributes('open')).toBeUndefined()
    productReadAccountEpoch.value++
    await settle()
    await wrapper.get('tbody button').trigger('click')
    await settle()
    await wrapper.get('dialog input').setValue('Fresh editor draft')
    const callsAfterSwitch = apiFetch.mock.calls.length
    finishSave!(response({}, success, 'Old editor failure'))
    await settle()
    expect(wrapper.get('dialog').attributes('open')).toBeDefined()
    expect((wrapper.get('dialog input').element as HTMLInputElement).value).toBe('Fresh editor draft')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.editor-actions .btn-primary').attributes('disabled')).toBeUndefined()
    expect(apiFetch).toHaveBeenCalledTimes(callsAfterSwitch)
  })

  it.each(['confirmation', 'receipt'])('rejects a stale deletion %s across an account switch', async stage => {
    await mountRoster()
    const read = apiFetch.getMockImplementation()!
    let finishConfirm: ((value: boolean) => void) | undefined
    let finishDelete: ((value: ReturnType<typeof response>) => void) | undefined
    if (stage === 'confirmation') appConfirm.mockImplementation(() => new Promise(resolve => { finishConfirm = resolve }))
    apiFetch.mockImplementation((url: string, init?: RequestInit) => init?.method === 'DELETE'
      ? new Promise(resolve => { finishDelete = resolve }) : read(url, init))
    await wrapper.get('tbody .danger-link').trigger('click')
    await settle()
    productReadAccountEpoch.value++
    await settle()
    const callsAfterSwitch = apiFetch.mock.calls.length
    if (stage === 'confirmation') finishConfirm!(true)
    else finishDelete!(response(null, false, 'Old deletion failure'))
    await settle()
    expect(apiFetch).toHaveBeenCalledTimes(callsAfterSwitch)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(renderedIds()).toEqual([26, 40, 60])
    expect(apiFetch.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(stage === 'confirmation' ? 0 : 1)
  })

  it('supports native touch dragging while preserving pre-hold scrolling', async () => {
    await mountRoster()
    const first = wrapper.get('tbody tr[data-roster-id]').element
    touch(first, 'touchstart')
    const ordinaryMove = touch(document, 'touchmove', 140)
    expect(ordinaryMove.defaultPrevented).toBe(false)
    await vi.advanceTimersByTimeAsync(600)
    touch(document, 'touchend', 140)
    expect(writes()).toEqual([])
    touch(first, 'touchstart')
    await vi.advanceTimersByTimeAsync(500)
    const dragMove = touch(document, 'touchmove', 200)
    expect(dragMove.defaultPrevented).toBe(true)
    await vi.advanceTimersByTimeAsync(32)
    expect(writes()).toEqual([])
    touch(document, 'touchend', 200)
    await settle()
    expect(writes()).toHaveLength(1)
    expect(writes()[0]?.[1].body).toBe(JSON.stringify({ position: 90, revision: 'owner-roster-revision' }))
  })
})
