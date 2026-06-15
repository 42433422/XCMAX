import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
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
  } as Response)
}

beforeEach(() => {
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
    mockFetchOnce({ success: true, data: [{ model_number: '9803', name: '蓝漆', price: 50, tin_spec: 28 }] })
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
    mockFetchOnce({ success: true, data: [{ model_number: '9803', name: '蓝漆', price: 42, tin_spec: 18 }] })
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
