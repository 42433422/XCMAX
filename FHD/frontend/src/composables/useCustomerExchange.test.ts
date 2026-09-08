import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCustomers } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/customers/useCustomers'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
const mocks = vi.hoisted(() => ({ importFile: vi.fn(), exportFile: vi.fn(), list: vi.fn(), push: vi.fn(), alert: vi.fn(), save: vi.fn() }))
vi.mock('@/api/customers', () => ({ default: { importCustomersExcel: mocks.importFile, exportCustomersXlsx: mocks.exportFile, getCustomers: mocks.list } }))
vi.mock('@/api/orders', () => ({ default: { getShipmentRecordUnits: async () => ({ data: [] }) } }))
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates: async () => ({ success: true, templates: [] }) } }))
vi.mock('@/composables/useCoreNavLabel', () => ({ useCoreNavLabel: () => '客户' }))
vi.mock('@/utils/appDialog', () => ({ appAlert: mocks.alert }))
vi.mock('@/utils', () => ({ downloadBlob: mocks.save }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
let control: ReturnType<typeof useCustomers>
let wrapper: ReturnType<typeof mount>
const uploadEvent = () => ({ target: { files: [new File(['fixture'], '客户.xlsx')], value: 'selected' } } as unknown as Event)
beforeEach(async () => {
  vi.clearAllMocks()
  mocks.list.mockResolvedValue({ success: true, data: [] })
  wrapper = mount(defineComponent({ setup() { control = useCustomers(); return () => h('div') } }))
  await flushPromises()
})
afterEach(() => wrapper.unmount())
describe('customer file actions', () => {
  it('opens the returned preview without claiming imported rows or refreshing the list', async () => {
    mocks.importFile.mockResolvedValue({ success: true, data: { run_id: 'owned-run', requires_confirmation: true } })
    const event = uploadEvent()
    await control.handleImport(event)
    expect(mocks.push).toHaveBeenCalledWith({ path: '/business-docking', query: { run_id: 'owned-run' } })
    expect(mocks.importFile.mock.calls[0][0].get('file').name).toBe('客户.xlsx')
    expect(mocks.alert).not.toHaveBeenCalled()
    expect(mocks.list).toHaveBeenCalledTimes(1)
    expect((event.target as HTMLInputElement).value).toBe('')
  })
  it('rejects a success response without a review receipt', async () => {
    mocks.importFile.mockResolvedValue({ success: true, data: { inserted: 200 } })
    await control.handleImport(uploadEvent())
    expect(mocks.push).not.toHaveBeenCalled()
    expect(mocks.alert).toHaveBeenCalledWith(expect.stringContaining('未取得客户导入预演'))
  })
  it('does not navigate to an old account run after account changes', async () => {
    let finish!: (value: unknown) => void
    mocks.importFile.mockReturnValue(new Promise(resolve => { finish = resolve }))
    const work = control.handleImport(uploadEvent())
    productReadAccountEpoch.value++
    finish({ success: true, data: { run_id: 'old-account', requires_confirmation: true } })
    await work
    expect(mocks.push).not.toHaveBeenCalled()
    expect(mocks.alert).not.toHaveBeenCalled()
  })
  it('downloads the standard customer workbook when no custom template is selected', async () => {
    const blob = new Blob(['workbook'])
    mocks.exportFile.mockResolvedValue({ blob: async () => blob })
    await control.exportCustomers()
    expect(mocks.exportFile).toHaveBeenCalledWith(undefined)
    expect(mocks.save).toHaveBeenCalledWith(blob, '购买单位列表.xlsx')
  })
  it('does not save a previous account download after blob reading', async () => {
    let finish!: (value: Blob) => void
    mocks.exportFile.mockResolvedValue({ blob: () => new Promise(resolve => { finish = resolve }) })
    const work = control.exportCustomers()
    await flushPromises()
    productReadAccountEpoch.value++
    finish(new Blob(['old-account']))
    await work
    expect(mocks.save).not.toHaveBeenCalled()
  })
})
