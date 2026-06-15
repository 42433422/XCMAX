import { describe, expect, it } from 'vitest';
import { materialsApi } from '../materials';

describe('materials api module', () => {
  it('exports CRUD and export helpers', () => {
    expect(typeof materialsApi.getMaterials).toBe('function');
    expect(typeof materialsApi.getMaterial).toBe('function');
    expect(typeof materialsApi.createMaterial).toBe('function');
    expect(typeof materialsApi.updateMaterial).toBe('function');
    expect(typeof materialsApi.deleteMaterial).toBe('function');
    expect(typeof materialsApi.batchDeleteMaterials).toBe('function');
    expect(typeof materialsApi.getLowStockMaterials).toBe('function');
    expect(typeof materialsApi.searchMaterials).toBe('function');
    expect(typeof materialsApi.exportMaterialsXlsx).toBe('function');
  });
});
