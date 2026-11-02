import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { CSSProperties } from 'vue'
import TemplateCandidatePreview from './TemplateCandidatePreview.vue'

type Props = InstanceType<typeof TemplateCandidatePreview>['$props']
type Cell = Props['layouts'][number]['rows'][number]['cells'][number]
const cell = (address: string, value: string, extra: Partial<Cell> = {}): Cell => ({
  cell: address, value, formula: false, rowspan: 1, colspan: 1, bold: false, italic: false,
  font_size: 11, font_color: '', fill: '', align: 'left', ...extra,
})
const layouts: Props['layouts'] = [
  { sheet: '生产单', widths: [18, 30, 12], truncated: false, rows: [
    { height: 24, cells: [cell('A1', '合成生产单', { colspan: 3, bold: true, font_size: 14, font_color: '112233', fill: 'DDEEFF', align: 'center' })] },
    { height: 18, cells: [cell('A2', '工序\n保持换行', { rowspan: 2, italic: true }), cell('B2', '=SUM(C3:C4)', { formula: true }), cell('C2', '<script>unsafe()</script>')] },
    { height: 18, cells: [cell('B3', '42'), cell('C3', '只读内容')] },
  ] },
  { sheet: '报价明细', widths: [24], truncated: true, rows: [{ height: 20, cells: [cell('A1', '报价明细末页片段')] }] },
]
const cellStyle = (item: Cell): CSSProperties => ({
  fontWeight: item.bold ? '700' : '400', fontStyle: item.italic ? 'italic' : 'normal',
  fontSize: `${item.font_size}px`, color: item.font_color ? `#${item.font_color}` : undefined,
  backgroundColor: item.fill ? `#${item.fill}` : undefined, textAlign: item.align as CSSProperties['textAlign'],
})
let wrapper: VueWrapper | undefined
let host: HTMLDivElement
let opener: HTMLButtonElement
let bodyStyle: string | null
beforeEach(() => {
  bodyStyle = document.body.getAttribute('style')
  opener = document.createElement('button'); opener.textContent = '打开候选预览'
  host = document.createElement('div'); document.body.append(opener, host); opener.focus()
})
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined
  host.remove(); opener.remove()
  if (bodyStyle === null) document.body.removeAttribute('style')
  else document.body.setAttribute('style', bodyStyle)
})
async function open(overrides: Partial<Props> = {}) {
  wrapper = mount(TemplateCandidatePreview, { attachTo: host, props: {
    title: '生产单 · 候选一', explanation: '保留工艺和原始表达式，供人工核对。', layouts, initialSheet: 0,
    selected: false, canSelect: true, cellStyle, ...overrides,
  } })
  await flushPromises()
  return new DOMWrapper(document.body.querySelector<HTMLElement>('.template-preview-dialog')!)
}

describe('TemplateCandidatePreview real workbook rendering', () => {
  it('keeps original text, formulas, merged cells and supplied formatting intact in a read-only preview', async () => {
    const dialog = await open({ title: '生产单 · 原件（只读）', readOnly: true })
    expect(dialog.attributes('aria-label')).toBe('生产单 · 原件（只读），放大预览')
    expect(dialog.get('header h3').text()).toBe('生产单 · 原件（只读）')
    expect(dialog.get('.template-preview-toolbar p').text()).toContain('保留工艺和原始表达式')
    expect(dialog.get('.template-preview-toolbar small').text()).toContain('公式显示表达式，未计算结果')
    const cells = dialog.findAll('td')
    expect(cells.map(item => item.text())).toEqual(['合成生产单', '工序\n保持换行', '=SUM(C3:C4)', '<script>unsafe()</script>', '42', '只读内容'])
    expect(cells[0].attributes('colspan')).toBe('3')
    expect(cells[1].attributes('rowspan')).toBe('2')
    expect((cells[0].element as HTMLElement).style).toMatchObject({ fontWeight: '700', fontSize: '14px', color: 'rgb(17, 34, 51)', backgroundColor: 'rgb(221, 238, 255)', textAlign: 'center' })
    expect((cells[1].element as HTMLElement).style.fontStyle).toBe('italic')
    const columnWidths = dialog.findAll('col').map(column => Number.parseFloat((column.element as HTMLElement).style.width))
    expect(columnWidths[1]).toBeGreaterThan(columnWidths[0]); expect(columnWidths[0]).toBeGreaterThan(columnWidths[2])
    expect(dialog.find('script').exists()).toBe(false)
    expect(dialog.find('footer').exists()).toBe(false)
    await cells[0].trigger('click')
    expect(wrapper!.emitted('select')).toBeUndefined()
    expect(wrapper!.emitted('close')).toBeUndefined()
  })

  it('opens the requested sheet, labels truncation and switches to the corresponding original table', async () => {
    const dialog = await open({ initialSheet: 1 })
    const select = dialog.get('select')
    expect((select.element as HTMLSelectElement).value).toBe('1')
    expect(select.findAll('option').map(option => option.text())).toEqual(['生产单', '报价明细（预览截断）'])
    expect(dialog.get('table').text()).toBe('报价明细末页片段')
    await select.setValue('0')
    expect(dialog.get('table').text()).toContain('合成生产单')
    expect(dialog.get('table').text()).not.toContain('报价明细末页片段')
    await select.setValue('1')
    expect(dialog.get('table').text()).toBe('报价明细末页片段')
  })

  it('uses the first available sheet for an unavailable initial selection and updates the candidate description', async () => {
    const dialog = await open({ initialSheet: 99 })
    expect((dialog.get('select').element as HTMLSelectElement).value).toBe('0')
    expect(dialog.get('table').text()).toContain('合成生产单')
    await wrapper!.setProps({ title: '生产单 · 候选二', explanation: '保留备注的新候选。' })
    expect(dialog.attributes('aria-label')).toBe('生产单 · 候选二，放大预览')
    expect(dialog.get('.template-preview-toolbar p').text()).toBe('保留备注的新候选。')
  })

  it('explains a missing layout without showing a fabricated worksheet or allowing selection', async () => {
    const dialog = await open({ layouts: [], canSelect: false })
    expect(dialog.get('.template-preview-viewport').text()).toBe('此版本无成品布局预览，请重新生成后核对。')
    expect(dialog.find('table').exists()).toBe(false)
    expect(dialog.find('select').exists()).toBe(false)
    const choose = dialog.get('footer button')
    expect((choose.element as HTMLButtonElement).disabled).toBe(true)
    ;(choose.element as HTMLButtonElement).click()
    expect(wrapper!.emitted('select')).toBeUndefined()
  })

  it('offers selection only when allowed and clearly marks an already selected candidate', async () => {
    const dialog = await open({ canSelect: false })
    const choose = dialog.get('footer button')
    expect(choose.text()).toBe('选择此模板')
    expect((choose.element as HTMLButtonElement).disabled).toBe(true)
    await wrapper!.setProps({ canSelect: true })
    expect((choose.element as HTMLButtonElement).disabled).toBe(false)
    await choose.trigger('click')
    expect(wrapper!.emitted('select')).toEqual([[]])
    await wrapper!.setProps({ selected: true })
    expect(dialog.get('footer').text()).toContain('当前已选模板')
    expect((choose.element as HTMLButtonElement).disabled).toBe(true)
    ;(choose.element as HTMLButtonElement).click()
    expect(wrapper!.emitted('select')).toHaveLength(1)
  })

  it.each(['close button', 'backdrop'] as const)('closes from the %s while clicks inside the paper remain safe', async action => {
    const dialog = await open()
    await dialog.get('table').trigger('click')
    expect(wrapper!.emitted('close')).toBeUndefined()
    if (action === 'close button') await dialog.get('header button').trigger('click')
    else await new DOMWrapper(document.body.querySelector<HTMLElement>('.template-preview-overlay')!).trigger('click')
    expect(wrapper!.emitted('close')).toEqual([[]])
    expect(wrapper!.emitted('select')).toBeUndefined()
  })

  it('keeps keyboard focus within the preview and restores the opener and scroll settings after Escape', async () => {
    document.body.style.setProperty('overflow', 'scroll', 'important')
    const dialog = await open()
    const close = dialog.get('header button').element as HTMLButtonElement
    const choose = dialog.get('footer button').element as HTMLButtonElement
    expect(document.activeElement).toBe(close)
    expect(document.body.style.overflow).toBe('hidden')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(choose)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(close)
    opener.focus()
    expect(document.activeElement).toBe(close)
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(escape)
    expect(escape.defaultPrevented).toBe(true)
    expect(wrapper!.emitted('close')).toEqual([[]])
    wrapper!.unmount(); wrapper = undefined
    expect(document.activeElement).toBe(opener)
    expect(document.body.style.overflow).toBe('scroll')
    expect(document.body.style.getPropertyPriority('overflow')).toBe('important')
  })

  it('allows worksheet scrolling while preventing wheel and touch scrolling on the backdrop', async () => {
    const dialog = await open()
    const overlay = document.body.querySelector<HTMLElement>('.template-preview-overlay')!
    for (const type of ['wheel', 'touchmove']) {
      const outside = new Event(type, { bubbles: true, cancelable: true })
      overlay.dispatchEvent(outside)
      expect(outside.defaultPrevented).toBe(true)
      const inside = new Event(type, { bubbles: true, cancelable: true })
      dialog.get('.template-preview-viewport').element.dispatchEvent(inside)
      expect(inside.defaultPrevented).toBe(false)
    }
    expect(wrapper!.emitted('close')).toBeUndefined()
  })
})
