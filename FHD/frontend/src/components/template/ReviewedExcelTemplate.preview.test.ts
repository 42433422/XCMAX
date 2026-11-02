import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

vi.mock('@/api/templatePreview', () => ({ default: { previewReviewedIntake: vi.fn() } }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn() } }))
const layout = (value: string, sheet = 'Sheet1') => ({
  sheet, widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false,
    rowspan: 2, colspan: 2, bold: true, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false,
})
let wrapper: VueWrapper
let host: HTMLElement
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')
const cards = () => wrapper.findAll('.reviewed-template__preview--a4')
beforeEach(async () => {
  host = document.createElement('div'); document.body.append(host)
  wrapper = mount(ReviewedExcelTemplate, { attachTo: host, props: { archiveOnSelect: true } })
  const state = wrapper.vm.$.setupState as Record<string, unknown>
  const proposal = { version: 'preview-v1', candidates: [0, 1, 2].map(i => ({ id: `candidate-${i}`, label: `候选${i + 1}`, explanation: `清理建议${i + 1}`, clear: [] })),
    model: { status: 'returned' }, result_previews: [0, 1, 2].map(i => ({ candidate_id: `candidate-${i}`, layout: [layout(`结果${i + 1}`), layout(`第二表${i + 1}`, 'Sheet2')], sha256: `${i}` })) }
  state.proposals = [proposal]
  state.review = { review_id: 'synthetic-preview', sheets: ['Sheet1', 'Sheet2'], cells: [], layout: [layout('原件')], proposal }
  await flushPromises()
})
afterEach(() => { wrapper.unmount(); host.remove(); vi.restoreAllMocks() })

describe('template enlarged preview', () => {
  it.each([0, 1, 2])('opens candidate %i from its border without changing selection, and switches actual sheets', async index => {
    await cards()[index].trigger('click'); await flushPromises()
    expect(dialog()?.textContent).toContain(`结果${index + 1}`)
    expect(dialog()?.textContent).toContain(`清理建议${index + 1}`)
    expect((wrapper.vm.$.setupState as Record<string, unknown>).candidateIndex).toBe(0)
    const cell = dialog()!.querySelector('td')!
    expect(cell.getAttribute('rowspan')).toBe('2')
    const select = dialog()!.querySelector('select')!
    select.value = '1'; select.dispatchEvent(new Event('change', { bubbles: true })); await flushPromises()
    expect(dialog()?.textContent).toContain(`第二表${index + 1}`)
    expect(dialog()?.querySelector('.template-preview-viewport')?.getAttribute('tabindex')).toBe('0')
  })

  it('keeps selection and detail actions separate from opening preview', async () => {
    await cards()[1].get('.reviewed-template__select-candidate').trigger('click'); await flushPromises()
    expect(dialog()).toBeNull()
    expect(cards()[1].get('.reviewed-template__select-candidate').attributes('aria-pressed')).toBe('true')
    await cards()[2].get('summary').trigger('click'); await flushPromises()
    expect(dialog()).toBeNull()
    expect(cards()[1].get('.reviewed-template__select-candidate').attributes('aria-pressed')).toBe('true')
  })

  it('focuses close, traps Tab, closes on Escape and returns focus to the preview button', async () => {
    const trigger = cards()[1].get('.reviewed-template__a4-open')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click'); await flushPromises()
    const close = dialog()!.querySelector<HTMLElement>('[aria-label="关闭放大预览"]')!
    expect(document.activeElement).toBe(close)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement?.textContent).toBe('选择此模板')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); await flushPromises()
    expect(dialog()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })

  it('closes by backdrop or close button, and selects explicitly inside the enlarged preview', async () => {
    await cards()[2].trigger('click'); await flushPromises()
    dialog()!.click(); await flushPromises(); expect(dialog()).not.toBeNull()
    document.querySelector<HTMLElement>('.template-preview-overlay')!.click(); await flushPromises(); expect(dialog()).toBeNull()
    await cards()[2].trigger('click'); await flushPromises()
    ;[...dialog()!.querySelectorAll('button')].find(button => button.textContent === '选择此模板')!.click(); await flushPromises()
    expect(dialog()).toBeNull()
    expect(cards()[2].get('.reviewed-template__select-candidate').attributes('aria-pressed')).toBe('true')
    await cards()[0].trigger('click'); await flushPromises()
    dialog()!.querySelector<HTMLElement>('[aria-label="关闭放大预览"]')!.click(); await flushPromises(); expect(dialog()).toBeNull()
  })

  it('disables selection while processing and closes stale previews when the review changes', async () => {
    const state = wrapper.vm.$.setupState as Record<string, unknown>
    state.busy = true
    await cards()[1].trigger('click'); await flushPromises()
    expect([...dialog()!.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === '选择此模板')!.disabled).toBe(true)
    state.review = null; await flushPromises()
    expect(dialog()).toBeNull()
  })

  it('locks background scrolling and restores prior overflow settings when the preview closes or unmounts', async () => {
    const prior = document.body.getAttribute('style')
    try {
      document.body.style.setProperty('overflow-x', 'auto')
      document.body.style.setProperty('overflow-y', 'scroll', 'important')
      await cards()[0].trigger('click'); await flushPromises()
      expect(document.body.style.overflow).toBe('hidden')
      dialog()!.querySelector<HTMLElement>('[aria-label="关闭放大预览"]')!.click(); await flushPromises()
      expect(document.body.style.overflowX).toBe('auto')
      expect(document.body.style.overflowY).toBe('scroll')
      expect(document.body.style.getPropertyPriority('overflow-y')).toBe('important')
      await cards()[0].trigger('click'); await flushPromises()
      ;(wrapper.vm.$.setupState as Record<string, unknown>).review = null; await flushPromises()
      expect(document.body.style.overflowY).toBe('scroll')
    } finally { if (prior === null) document.body.removeAttribute('style'); else document.body.setAttribute('style', prior) }
  })
})
