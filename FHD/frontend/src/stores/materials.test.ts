import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const api = vi.hoisted(() => ({
  getMaterials: vi.fn(),
  createMaterial: vi.fn(),
  updateMaterial: vi.fn(),
  deleteMaterial: vi.fn(),
  batchDeleteMaterials: vi.fn(),
  exportMaterialsXlsx: vi.fn(),
}))

vi.mock('../api/materials', () => ({ default: api }))

import { useMaterialsStore } from './materials'

describe('materials store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(api).forEach((fn) => fn.mockReset())
  })

  it('fetchMaterials success populates list and computeds', async () => {
    api.getMaterials.mockResolvedValue({
      success: true,
      data: [
        { id: 1, quantity: 2, min_stock: 5, category: 'A' },
        { id: 2, quantity: 9, min_stock: 5, category: 'B' },
        { id: 3, quantity: 1, min_stock: 5, category: 'A' },
      ],
      total: 3,
    })
    const s = useMaterialsStore()
    const r = await s.fetchMaterials({ page: 1 })
    expect(r.success).toBe(true)
    expect(s.materialCount).toBe(3)
    expect(s.lowStockMaterials).toHaveLength(2)
    expect(s.categories).toEqual(['A', 'B'])
  })

  it('fetchMaterials returns failure when api unsuccessful', async () => {
    api.getMaterials.mockResolvedValue({ success: false, message: '失败X' })
    const s = useMaterialsStore()
    const r = await s.fetchMaterials()
    expect(r.success).toBe(false)
    expect(s.error).toBe('失败X')
  })

  it('fetchMaterials catches thrown error', async () => {
    api.getMaterials.mockRejectedValue(new Error('boom'))
    const s = useMaterialsStore()
    const r = await s.fetchMaterials()
    expect(r.success).toBe(false)
    expect(s.error).toBe('boom')
  })

  it('createMaterial success refetches', async () => {
    api.createMaterial.mockResolvedValue({ success: true })
    api.getMaterials.mockResolvedValue({ success: true, data: [] })
    const s = useMaterialsStore()
    const r = await s.createMaterial({ name: 'x' } as never)
    expect(r.success).toBe(true)
    expect(api.getMaterials).toHaveBeenCalled()
  })

  it('createMaterial failure path', async () => {
    api.createMaterial.mockResolvedValue({ success: false })
    const s = useMaterialsStore()
    const r = await s.createMaterial({} as never)
    expect(r.success).toBe(false)
    expect(s.error).toBe('创建原材料失败')
  })

  it('updateMaterial success and failure', async () => {
    api.updateMaterial.mockResolvedValueOnce({ success: true })
    api.getMaterials.mockResolvedValue({ success: true, data: [] })
    const s = useMaterialsStore()
    expect((await s.updateMaterial(1, {} as never)).success).toBe(true)
    api.updateMaterial.mockRejectedValueOnce(new Error('upd'))
    expect((await s.updateMaterial(1, {} as never)).success).toBe(false)
    expect(s.error).toBe('upd')
  })

  it('deleteMaterial removes row on success', async () => {
    api.getMaterials.mockResolvedValue({ success: true, data: [{ id: 1 }, { id: 2 }] })
    api.deleteMaterial.mockResolvedValue({ success: true })
    const s = useMaterialsStore()
    await s.fetchMaterials()
    const r = await s.deleteMaterial(1)
    expect(r.success).toBe(true)
    expect(s.materials.find((m) => m.id === 1)).toBeUndefined()
  })

  it('deleteMaterial failure path', async () => {
    api.deleteMaterial.mockResolvedValue({ success: false, message: 'no' })
    const s = useMaterialsStore()
    expect((await s.deleteMaterial(9)).success).toBe(false)
  })

  it('batchDelete filters ids on success', async () => {
    api.getMaterials.mockResolvedValue({ success: true, data: [{ id: 1 }, { id: 2 }, { id: 3 }] })
    api.batchDeleteMaterials.mockResolvedValue({ success: true })
    const s = useMaterialsStore()
    await s.fetchMaterials()
    const r = await s.batchDelete([1, 3])
    expect(r.success).toBe(true)
    expect(s.materials.map((m) => m.id)).toEqual([2])
  })

  it('batchDelete catches error', async () => {
    api.batchDeleteMaterials.mockRejectedValue(new Error('batch'))
    const s = useMaterialsStore()
    expect((await s.batchDelete([1])).success).toBe(false)
    expect(s.error).toBe('batch')
  })

  it('exportMaterials delegates to api', async () => {
    api.exportMaterialsXlsx.mockResolvedValue({} as Response)
    const s = useMaterialsStore()
    await s.exportMaterials({ q: 'x' })
    expect(api.exportMaterialsXlsx).toHaveBeenCalledWith({ q: 'x' })
  })
})
