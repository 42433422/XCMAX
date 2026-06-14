import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), download: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

import materialsApi from './materials'

beforeEach(() => {
  for (const fn of Object.values(apiMock)) fn.mockReset().mockResolvedValue({ success: true })
})

describe('materialsApi', () => {
  it('covers all endpoints', async () => {
    await materialsApi.getMaterials({ page: 1 })
    await materialsApi.getMaterial(1)
    await materialsApi.createMaterial({ name: 'a' } as never)
    await materialsApi.updateMaterial(1, { name: 'b' } as never)
    await materialsApi.deleteMaterial(1)
    await materialsApi.batchDeleteMaterials([1, 2])
    await materialsApi.getLowStockMaterials()
    await materialsApi.exportMaterialsXlsx({ unit: 'u' })
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.put).toHaveBeenCalled()
    expect(apiMock.delete).toHaveBeenCalled()
    expect(apiMock.download).toHaveBeenCalled()
  })

  it('searchMaterials only attaches provided params', async () => {
    await materialsApi.searchMaterials('q', '')
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/materials', { search: 'q' })
    await materialsApi.searchMaterials('', 'cat')
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/materials', { category: 'cat' })
    await materialsApi.searchMaterials('', '')
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/materials', {})
  })
})
