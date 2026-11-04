import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

vi.mock('@/api/templatePreview', () => ({ default: {} }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn().mockResolvedValue(null) } }))
type Upload = { file: File; requestKey: string }
type State = { archiveAssets: { id: string; name: string; state: string; versions: never[] }[]; versionUploads: Record<string, Upload>; busy: boolean }
let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })
async function archivePicker() {
  wrapper = mount(ReviewedExcelTemplate, { attachTo: document.body })
  const state = wrapper.vm.$.setupState as unknown as State
  state.archiveAssets = [
    { id: 'asset-a', name: '合成档案甲.xlsx', state: 'active', versions: [] },
    { id: 'asset-b', name: '合成档案乙.xlsx', state: 'active', versions: [] },
  ]
  await flushPromises()
  const pickers = wrapper.findAll('.reviewed-template__version-picker')
  const inputs = pickers.map(picker => picker.get<HTMLInputElement>('input'))
  const buttons = pickers.map(picker => picker.get<HTMLButtonElement>('button'))
  async function select(index: number, file?: File) {
    Object.defineProperty(inputs[index].element, 'files', { configurable: true, value: file ? [file] : [] })
    await inputs[index].trigger('change')
  }
  return { state, pickers, inputs, buttons, select }
}

it('uses each archive’s own native picker and labels the platform buttons', async () => {
  const { inputs, buttons, pickers } = await archivePicker()
  const clicks = inputs.map(input => vi.spyOn(input.element, 'click').mockImplementation(() => undefined))
  for (let index = 0; index < 2; index += 1) {
    expect(buttons[index].classes()).toEqual(expect.arrayContaining(['btn', 'btn-sm', 'btn-secondary']))
    expect(buttons[index].attributes('type')).toBe('button')
    expect(buttons[index].attributes('aria-label')).toContain(index ? '档案乙' : '档案甲')
    expect(inputs[index].attributes('accept')).toBe('.xlsx,.xls')
    expect(inputs[index].attributes('tabindex')).toBe('-1')
    expect(pickers[index].get('[role="status"]').text()).toBe('未选择文件')
    await buttons[index].trigger('click')
    expect(clicks[index]).toHaveBeenCalledTimes(1)
  }
  expect(clicks[0]).toHaveBeenCalledTimes(1)
})

it('keeps archive selections separate, retains them on cancellation, and resets same-file selection', async () => {
  const { state, pickers, inputs, select } = await archivePicker()
  const first = new File(['synthetic-a'], '甲版本.xlsx')
  const second = new File(['synthetic-b'], '乙版本.xlsx')
  await select(0, first); await select(1, second)
  const firstKey = state.versionUploads['asset-a'].requestKey
  const secondKey = state.versionUploads['asset-b'].requestKey
  await select(0)
  expect(state.versionUploads['asset-a'].requestKey).toBe(firstKey)
  expect(pickers.map(picker => picker.get('[role="status"]').text())).toEqual([first.name, second.name])
  Object.defineProperty(inputs[0].element, 'value', { configurable: true, writable: true, value: 'C:\\fakepath\\甲版本.xlsx' })
  await select(0, first)
  expect(inputs[0].element.value).toBe('')
  expect(state.versionUploads['asset-a'].file.name).toBe(first.name)
  expect(state.versionUploads['asset-a'].requestKey).not.toBe(firstKey)
  expect(state.versionUploads['asset-b'].requestKey).toBe(secondKey)
})

it('disables both archive pickers and keeps selections unchanged while processing', async () => {
  const { state, buttons, inputs, select } = await archivePicker()
  await select(0, new File(['synthetic'], '已选.xlsx'))
  const requestKey = state.versionUploads['asset-a'].requestKey
  state.busy = true; await flushPromises()
  for (const control of [...inputs, ...buttons]) expect(control.element.disabled).toBe(true)
  await select(0, new File(['different'], '不应替换.xlsx'))
  await select(1, new File(['different'], '不应加入.xlsx'))
  expect(state.versionUploads['asset-a'].file.name).toBe('已选.xlsx')
  expect(state.versionUploads['asset-a'].requestKey).toBe(requestKey)
  expect(state.versionUploads['asset-b']).toBeUndefined()
  state.busy = false; await flushPromises()
  expect(buttons[0].element.disabled).toBe(false)
})
