import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({ archiveClassifyExcel: vi.fn(), archiveAssets: vi.fn(), classifyArchiveVersion: vi.fn(), downloadArchiveVersion: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/auth', () => ({ authApi: { validateSession: vi.fn() } }))
function classified(name: string) {
  return { name, status: 'classified', classification_id: name, version: 'v1', sheets: [{ sheet: 'Sheet1', labels: ['unknown'], checked_cells: 1, evidence: [],
    regions: [{ range: 'A1:D4', labels: ['unknown'], checked_cells: 1, parent_heading: '', dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }] }] }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((finish, fail) => { resolve = finish; reject = fail })
  return { promise, resolve, reject }
}
let wrapper: VueWrapper | undefined
let actor = 'A'
function account(id: string) {
  actor = id
  updateProductReadAccountScope({ tenantId: 1, localUserId: id, accountKind: 'local' })
}
async function choose(names: string[]) {
  const input = wrapper!.get('input[type="file"][multiple]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: names.map(name => new File(['private source'], name)) })
  await input.trigger('change'); await flushPromises()
}
beforeEach(() => {
  vi.clearAllMocks(); invalidateEnterpriseSessionCache(); account('A')
  api.archiveClassifyExcel.mockReset().mockImplementation(async (form: FormData) => classified((form.get('file') as File).name))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('reviewed workbook account and component ownership', () => {
  it.each([['B', 'resolve'], ['B', 'reject'], ['A', 'resolve'], ['A', 'reject']] as const)('retires the entire A batch after ending at %s with a late %s', async (finalAccount, completion) => {
    const first = deferred<ReturnType<typeof classified>>()
    const trace: { actor: string; name: string }[] = []
    api.archiveClassifyExcel.mockImplementation((form: FormData) => {
      trace.push({ actor, name: (form.get('file') as File).name })
      return trace.length === 1 ? first.promise : Promise.resolve(classified('unexpected.xlsx'))
    })
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await choose(['A-first.xlsx', 'A-second.xlsx'])
    account('B'); if (finalAccount === 'A') account('A')
    await flushPromises()
    const stages = wrapper.emitted('stage')?.length
    if (completion === 'resolve') first.resolve(classified('A-first.xlsx'))
    else first.reject(new Error('old A error'))
    await flushPromises()
    expect(trace).toEqual([{ actor: 'A', name: 'A-first.xlsx' }])
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('A-first.xlsx')
    expect(wrapper.text()).not.toContain('old A error')
    expect(wrapper.emitted('stage')?.length).toBe(stages)
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('stops after logout even when the account identifier has not changed', async () => {
    const first = deferred<ReturnType<typeof classified>>()
    api.archiveClassifyExcel.mockReturnValue(first.promise)
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await choose(['A-first.xlsx', 'A-second.xlsx'])
    invalidateEnterpriseSessionCache()
    first.resolve(classified('A-first.xlsx')); await flushPromises()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
  })

  it('does not continue or emit when the component is unmounted during the first file', async () => {
    const first = deferred<ReturnType<typeof classified>>()
    api.archiveClassifyExcel.mockReturnValue(first.promise)
    const stage = vi.fn(), saved = vi.fn()
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true, onStage: stage, onSaved: saved } })
    await choose(['A-first.xlsx', 'A-second.xlsx'])
    const old = wrapper, stages = stage.mock.calls.length
    old.unmount(); wrapper = undefined
    first.resolve(classified('A-first.xlsx')); await flushPromises()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(stage.mock.calls.length).toBe(stages)
    expect(saved).not.toHaveBeenCalled()
  })

  it('keeps the new B batch busy when an old A completion arrives', async () => {
    const oldA = deferred<ReturnType<typeof classified>>(), currentB = deferred<ReturnType<typeof classified>>()
    const trace: string[] = []
    api.archiveClassifyExcel.mockImplementation((form: FormData) => {
      const name = (form.get('file') as File).name; trace.push(`${actor}:${name}`)
      return name === 'A-first.xlsx' ? oldA.promise : name === 'B-first.xlsx' ? currentB.promise : Promise.resolve(classified(name))
    })
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await choose(['A-first.xlsx', 'A-second.xlsx'])
    account('B'); await flushPromises(); await choose(['B-first.xlsx', 'B-second.xlsx'])
    expect(trace).toEqual(['A:A-first.xlsx', 'B:B-first.xlsx'])
    expect(wrapper.get('input[type="file"][multiple]').attributes('disabled')).toBeDefined()
    const stages = wrapper.emitted('stage')?.length
    oldA.resolve(classified('A-first.xlsx')); await flushPromises()
    expect(wrapper.get('input[type="file"][multiple]').attributes('disabled')).toBeDefined()
    expect(wrapper.emitted('stage')?.length).toBe(stages)
    currentB.resolve(classified('B-first.xlsx')); await flushPromises()
    expect(trace).toEqual(['A:A-first.xlsx', 'B:B-first.xlsx', 'B:B-second.xlsx'])
    expect(wrapper.findAll('.classification-region')).toHaveLength(2)
    expect(wrapper.text()).not.toContain('A-first.xlsx')
  })

  it('archives every file normally when component and full session scope remain current', async () => {
    const trace: string[] = []
    api.archiveClassifyExcel.mockImplementation(async (form: FormData) => {
      const name = (form.get('file') as File).name; trace.push(`${actor}:${name}`); return classified(name)
    })
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await choose(['A-first.xlsx', 'A-second.xlsx'])
    expect(trace).toEqual(['A:A-first.xlsx', 'A:A-second.xlsx'])
    expect(wrapper.findAll('.classification-region')).toHaveLength(2)
    expect(wrapper.get('input[type="file"][multiple]').attributes('disabled')).toBeUndefined()
  })

  it.each(['分类此版本', '重新分类（保留历史）'])('does not restore an A archive via %s when bytes arrive after switching to B', async (action) => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const bytes = deferred<Blob>()
    api.archiveAssets.mockResolvedValue({ assets: [{ id: 'asset-A', name: 'A-private.xlsx', state: 'active', versions: [{ id: 'version-A', version: 1, status: 'ready', sha256: 'sha', classification_id: 'c-A' }] }] })
    api.classifyArchiveVersion.mockResolvedValue(classified('A-private.xlsx'))
    api.downloadArchiveVersion.mockResolvedValue({ blob: () => bytes.promise })
    wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
    await wrapper.findAll('button').find(button => button.text() === '查看原件档案')!.trigger('click'); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === action)!.trigger('click'); await flushPromises()
    const form = api.classifyArchiveVersion.mock.calls.at(-1)![1] as FormData
    expect(form.get('reclassify')).toBe(action === '分类此版本' ? null : 'true')
    expect(form.get('expected_classification_id')).toBe(action === '分类此版本' ? null : 'c-A')
    account('B')
    bytes.resolve(new Blob(['A original bytes'])); await flushPromises()
    expect(wrapper.text()).not.toContain('A-private.xlsx')
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(api.archiveAssets).toHaveBeenCalledTimes(1)
  })
})
