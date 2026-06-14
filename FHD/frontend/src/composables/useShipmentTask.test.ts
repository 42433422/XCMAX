import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useShipmentTask } from './useShipmentTask'
import type { ShipmentTask } from './useShipmentTask'

describe('useShipmentTask', () => {
  const addAndSaveMessage = vi.fn()
  const currentTask = ref<ShipmentTask | null>(null)

  function api() {
    return useShipmentTask({ addAndSaveMessage }, currentTask)
  }

  it('getTaskOrderNumber returns empty without task', () => {
    expect(api().getTaskOrderNumber(null)).toBe('')
  })

  it('getTaskOrderNumber reads explicit order number', () => {
    const task: ShipmentTask = {
      type: 'shipment_generate',
      order_number: 'SO-001',
    }
    expect(api().getTaskOrderNumber(task)).toBe('SO-001')
  })

  it('getTaskOrderNumber shows pending label for shipment_generate', () => {
    const task: ShipmentTask = { type: 'shipment_generate', completed: false }
    expect(api().getTaskOrderNumber(task)).toBe('待生成')
  })

  it('getTaskTableColumns returns shipment preview columns', () => {
    const task: ShipmentTask = {
      type: 'shipment_generate',
      items: [{ 型号: 'A1', 桶数: 2 }],
    }
    const cols = api().getTaskTableColumns(task)
    expect(cols.length).toBeGreaterThan(0)
    expect(cols).toContain('型号')
  })

  it('getTaskTableItems normalizes empty cells to dash', () => {
    const task: ShipmentTask = {
      type: 'shipment_generate',
      items: [{ 型号: 'A1', 桶数: '', 规格: null }],
    }
    const rows = api().getTaskTableItems(task)
    expect(rows[0]['桶数']).toBe('-')
  })

  it('handleModifyCommand is callable when task present', () => {
    currentTask.value = {
      type: 'shipment_generate',
      items: [],
      payload: { params: { products: [] } },
    }
    const { handleModifyCommand } = api()
    expect(() => handleModifyCommand('删除 X100')).not.toThrow()
  })
})
