import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MatureChat from './MatureChat.vue'
vi.mock('vue-advanced-chat', () => ({ register: () => {
  if (!customElements.get('vue-advanced-chat')) customElements.define('vue-advanced-chat', class extends HTMLElement {
    constructor() {
      super()
      const shadow = this.attachShadow({ mode: 'open' })
      for (const name of ['room-header-info', 'room-options', 'room-header-avatar', 'messages-empty']) {
        const slot = document.createElement('slot')
        slot.name = name
        shadow.append(slot)
      }
    }
  })
} }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach(w => w.unmount()))
async function setup(extra = {}) {
  const wrapper = mount(MatureChat, { props: { roomId: 'tenant-group', title: '员工群', rows: [
    { id: 'host-42', mine: false, sender: '审核员', label: '待复核', body: '不能据此验收通过', at: null },
  ], ...extra } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function dispatch(wrapper: ReturnType<typeof mount>, type: string, data: object) {
  wrapper.get('vue-advanced-chat').element.dispatchEvent(new CustomEvent(type, { detail: [data] }))
}
describe('mature chat host adapter', () => {
  it('projects identity, actions, avatar and empty content into native shadow slots', async () => {
    const click = vi.fn()
    const w = mount(MatureChat, { props: { roomId: 'g', title: '员工群', rows: [] },
      slots: { actions: '<button class="native-action">成员</button>', avatar: '<img alt="群头像" />' } })
    wrappers.push(w)
    await flushPromises()
    const host = w.get('vue-advanced-chat').element
    for (const name of ['room-header-info', 'room-options', 'room-header-avatar', 'messages-empty']) {
      const slot = host.shadowRoot!.querySelector<HTMLSlotElement>(`slot[name="${name}"]`)!
      expect(slot.assignedElements()).toEqual([host.querySelector(`[slot="${name}"]`)])
    }
    w.get('.native-action').element.addEventListener('click', click)
    await w.get('.native-action').trigger('click')
    expect(click).toHaveBeenCalledOnce()
    expect(w.get('[slot="room-header-info"]').text()).toContain('员工群')
    expect(w.get('[slot="room-header-avatar"] img').attributes('alt')).toBe('群头像')
  })
  it('preserves source IDs and review provenance without fabricating read receipts', async () => {
    const w = await setup()
    const row = JSON.parse(w.get('vue-advanced-chat').attributes('messages'))[0]
    expect(row).toMatchObject({ _id: 'host-42', username: '审核员 · 待复核', timestamp: '', senderId: 'peer' })
    expect(row.seen).toBeUndefined()
    expect(row.saved).toBeUndefined()
  })
  it('bridges upstream CustomEvent arrays into the existing draft and send contracts', async () => {
    const w = await setup()
    dispatch(w, 'typing-message', { message: '第一行\n第二行' })
    dispatch(w, 'send-message', { content: '第一行\n第二行' })
    expect(w.emitted('update:draft')?.at(-1)).toEqual(['第一行\n第二行'])
    expect(w.emitted('send')).toEqual([['第一行\n第二行']])
  })
  it('blocks duplicate dispatch while busy and retains over-limit text for correction', async () => {
    const w = await setup({ disabled: true })
    dispatch(w, 'send-message', { content: '重复派工' })
    expect(w.emitted('send')).toBeUndefined()
    await w.setProps({ disabled: false })
    dispatch(w, 'send-message', { content: '字'.repeat(4001) })
    await flushPromises()
    expect(w.emitted('send')).toBeUndefined()
    expect(w.emitted('update:draft')?.at(-1)?.[0]).toHaveLength(4001)
    expect(w.get('[role="alert"]').text()).toContain('4000')
  })
  it('does not reload history on the upstream initial reset event', async () => {
    const w = await setup({ hasMore: true })
    dispatch(w, 'fetch-messages', { options: { reset: true } })
    await flushPromises()
    expect(w.emitted('load-older')).toBeUndefined()
    dispatch(w, 'fetch-messages', { options: {} })
    expect(w.emitted('load-older')).toHaveLength(1)
  })
})
