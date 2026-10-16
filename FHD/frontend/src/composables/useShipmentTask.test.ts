import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'

function makeMessages() {
  return { addAndSaveMessage: vi.fn().mockResolvedValue(undefined) }
}

function shipmentTask(products: unknown[] = []): ShipmentTask {
  return {
    type: 'shipment_generate',
    completed: false,
    payload: { params: { products: products as never, unit_name: '甲单位' } },
    items: [],
  }
}

function mockFetchOnce(body: unknown, ok = true) {
  ;(globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok,
    json: async () => body,
    headers: { get: () => 'application/json' },
  } as Response)
}

beforeEach(() => {
  useModsStore().isLoaded = true
  globalThis.fetch = vi.fn()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('useShipmentTask handleModifyCommand', () => {
  it('returns false when no task or wrong type or completed', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    expect(await s.handleModifyCommand('再加 1桶9803规格28')).toBe(false)
    task.value = { type: 'other' }
    expect(await s.handleModifyCommand('再加 1桶9803规格28')).toBe(false)
    task.value = { type: 'shipment_generate', completed: true }
    expect(await s.handleModifyCommand('再加 1桶9803规格28')).toBe(false)
  })

  it('returns false for non-command message', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask())
    const s = useShipmentTask(m, task)
    expect(await s.handleModifyCommand('随便聊聊')).toBe(false)
  })

  it('add command fetches meta and appends product', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask())
    const s = useShipmentTask(m, task)
    mockFetchOnce({
      success: true,
      data: [{ model_number: '9803', name: '蓝漆', price: 50, tin_spec: 28 }],
    })
    const ok = await s.handleModifyCommand('再加 1桶9803规格28')
    expect(ok).toBe(true)
    expect(task.value!.payload!.params!.products).toHaveLength(1)
    expect(m.addAndSaveMessage).toHaveBeenCalled()
  })

  it('remove command deletes matching product', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask([{ model_number: '9803', quantity_tins: 1, tin_spec: 28 }]))
    const s = useShipmentTask(m, task)
    const ok = await s.handleModifyCommand('删除 9803')
    expect(ok).toBe(true)
    expect(task.value!.payload!.params!.products).toHaveLength(0)
  })

  it('remove command reports missing model', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask([{ model_number: 'AAA' }]))
    const s = useShipmentTask(m, task)
    await s.handleModifyCommand('删除 9803')
    expect(m.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('未找到'), 'ai')
  })

  it('edit command updates existing product', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask([{ model_number: '9803', quantity_tins: 1, tin_spec: 10 }]))
    const s = useShipmentTask(m, task)
    const ok = await s.handleModifyCommand('把9803改成2桶规格28')
    expect(ok).toBe(true)
    expect(task.value!.payload!.params!.products[0].tin_spec).toBe(28)
  })
})

describe('useShipmentTask order number and enrichment', () => {
  it('fetchNextOrderNumber returns first valid number', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    mockFetchOnce({ success: true, data: { order_number: 'SO-1A' } })
    expect(await s.fetchNextOrderNumber()).toBe('SO-1A')
  })

  it('fetchNextOrderNumber returns empty when all fail', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    mockFetchOnce({}, false)
    mockFetchOnce({}, false)
    mockFetchOnce({}, false)
    expect(await s.fetchNextOrderNumber()).toBe('')
  })

  it('hydrateTaskOrderNumber sets order number on task', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask())
    const s = useShipmentTask(m, task)
    mockFetchOnce({ success: true, data: { order_number: 'SO-9A' } })
    await s.hydrateTaskOrderNumber(task.value!)
    expect(task.value!.customOrderNumber).toBe('SO-9A')
  })

  it('enrichShipmentPreviewProducts fills missing name and price', async () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(shipmentTask([{ model_number: '9803' }]))
    const s = useShipmentTask(m, task)
    mockFetchOnce({
      success: true,
      data: [{ model_number: '9803', name: '蓝漆', price: 42, tin_spec: 18 }],
    })
    await s.enrichShipmentPreviewProducts(task.value!)
    expect(task.value!.payload!.params!.products[0].name).toBe('蓝漆')
  })
})

describe('useShipmentTask table helpers', () => {
  it('getTaskTableColumns returns preview columns for shipment', () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    const t = shipmentTask()
    t.items = [{ 型号: 'X' }]
    expect(s.getTaskTableColumns(t)).toContain('型号')
    expect(s.getTaskTableColumns({ type: 'other', items: [] } as ShipmentTask)).toEqual([])
  })

  it('getTaskTableItems normalizes shipment rows', () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    const t = shipmentTask()
    t.items = [{ 型号: '9803', 桶数: 2 }]
    const rows = s.getTaskTableItems(t)
    expect(rows[0]['型号']).toBe('9803')
    expect(rows[0]['单价']).toBe('-')
  })

  it('getTaskOrderNumber resolves explicit or placeholder', () => {
    const m = makeMessages()
    const task = ref<ShipmentTask | null>(null)
    const s = useShipmentTask(m, task)
    expect(s.getTaskOrderNumber(null)).toBe('')
    expect(s.getTaskOrderNumber({ type: 'x', order_number: 'EXP-1' } as ShipmentTask)).toBe('EXP-1')
    expect(s.getTaskOrderNumber(shipmentTask())).toBe('待生成')
  })
})

describe('shipment preview fallbacks and asynchronous edits', () => {
  it.each([
    [[{ name: 'unrelated' }, { product_name: 'Paint 98-03', unit_price: '12.5', specification: '2' }], 'Paint 98-03'],
    [[{ name: 'unrelated', model_number: '0000' }, { name: 'Model match', model_number: '9803-EX', spec: 2 }], 'Model match'],
    [[{ name: 'Fallback', price: 'invalid' }, { name: 'Other' }], 'Fallback'],
  ])('selects matching names, partial models, and finally the first returned product', async (data, name) => {
    const task = ref<ShipmentTask | null>(shipmentTask([{ model_number: '9803', quantity_tins: 2 }]))
    const s = useShipmentTask(makeMessages(), task)
    mockFetchOnce({ success: true, data: [] })
    mockFetchOnce({ success: true, data })
    await s.enrichShipmentPreviewProducts(task.value!)
    expect(task.value!.payload!.params!.products[0].name).toBe(name)
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('unit=')
    expect(String(vi.mocked(fetch).mock.calls[1][0])).not.toContain('unit=')
    if (name === 'Paint 98-03') expect(task.value!.items![0]).toMatchObject({ 单价: '12.50', 总价: '50.00' })
  })
  it('keeps a usable unpriced preview when both metadata lookups fail', async () => {
    const messages = makeMessages(), task = ref<ShipmentTask | null>(shipmentTask())
    const s = useShipmentTask(messages, task)
    mockFetchOnce({ success: false }); mockFetchOnce({ success: true, data: null })
    expect(await s.handleModifyCommand('再加 1桶9803规格28')).toBe(true)
    expect(task.value!.items![0]).toMatchObject({ 型号: '9803', 单价: '-', 总价: '-' })
    expect(messages.addAndSaveMessage).toHaveBeenCalledWith('已加入：9803，1桶，规格28。', 'ai')
  })
  it('does not query empty or already complete products and reports edits to absent models', async () => {
    const messages = makeMessages(), task = ref<ShipmentTask | null>(shipmentTask([{ model_number: '9803', name: '蓝漆', unit_price: 5 }, {}]))
    const s = useShipmentTask(messages, task)
    await s.enrichShipmentPreviewProducts(shipmentTask())
    await s.enrichShipmentPreviewProducts(task.value!)
    expect(fetch).not.toHaveBeenCalled()
    await s.handleModifyCommand('把9804改成2桶规格28')
    expect(messages.addAndSaveMessage).toHaveBeenCalledWith(expect.stringContaining('请先"再加 9804'), 'ai')
  })
  it('preserves old unit, name, quantity, and price when rebuilding a partial preview', () => {
    const task = shipmentTask(), s = useShipmentTask(makeMessages(), ref(null))
    task.payload = undefined
    task.items = [{ 单位: '旧单位', 型号: '9803', 产品名称: '旧产品', 桶数: 3, 规格: 2, 单价: 4 }, {}]
    s.updateShipmentTaskPreview(task, [{ model_number: '9803' }, { quantity: 0, spec: 0 }])
    expect(task.items).toEqual([
      { 单位: '旧单位', 型号: '9803', 产品名称: '旧产品', 桶数: 3, 规格: 2, 单价: '4.00', 总价: '24.00' },
      { 单位: '旧单位', 型号: '-', 产品名称: '-', 桶数: 1, 规格: 10, 单价: '-', 总价: '-' }])
    expect(task.description).toContain('预估总价 ¥24.00')
    expect(s.getTaskTableColumns({ type: 'other', items: [{ custom: 0 }] })).toEqual(['custom'])
    expect(s.getTaskTableItems({ type: 'other', items: [null, false, { custom: 0 }] })).toEqual([{ custom: 0 }])
    expect(s.getTaskTableItems({ type: 'other' })).toEqual([])
    expect(s.getTaskOrderNumber({ type: 'other' })).toBe('')
  })
  it.each(['replace', 'customize', 'force'] as const)('does not overwrite concurrent user intent during order allocation: %s', async (action) => {
    const task = ref<ShipmentTask | null>(shipmentTask()), s = useShipmentTask(makeMessages(), task)
    let resolve!: (value: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done }))
    const original = task.value!, pending = s.hydrateTaskOrderNumber(original, { force: action === 'force' })
    await Promise.resolve()
    if (action === 'replace') task.value = shipmentTask()
    else original.customOrderNumber = 'MANUAL'
    resolve({ ok: true, json: async () => ({ success: true, data: { order_number: 'SO-NEW' } }), headers: { get: () => 'application/json' } } as Response)
    await pending
    expect(original.customOrderNumber).toBe(action === 'replace' ? undefined : action === 'force' ? 'SO-NEW' : 'MANUAL')
  })
  it('skips completed and customized orders, and leaves allocation failures empty', async () => {
    const task = ref<ShipmentTask | null>(shipmentTask()), s = useShipmentTask(makeMessages(), task)
    for (const ignored of [{ type: 'other' }, { type: 'shipment_generate', completed: true }, { ...shipmentTask(), customOrderNumber: 'MANUAL' }]) await s.hydrateTaskOrderNumber(ignored)
    expect(fetch).not.toHaveBeenCalled()
    for (let i = 0; i < 3; i++) mockFetchOnce({ success: false })
    await s.hydrateTaskOrderNumber(task.value!)
    expect(task.value!.customOrderNumber).toBeUndefined()
  })
})
