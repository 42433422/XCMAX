import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useProductsStore } from './products';

const mockGetProducts = vi.fn();
const mockCreateProduct = vi.fn();
const mockUpdateProduct = vi.fn();
const mockDeleteProduct = vi.fn();
const mockBatchDelete = vi.fn();

vi.mock('../api/products', () => ({
  default: {
    getProducts: (...args: unknown[]) => mockGetProducts(...args),
    createProduct: (...args: unknown[]) => mockCreateProduct(...args),
    updateProduct: (...args: unknown[]) => mockUpdateProduct(...args),
    deleteProduct: (...args: unknown[]) => mockDeleteProduct(...args),
    batchDeleteProducts: (...args: unknown[]) => mockBatchDelete(...args),
  },
}));

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe('products store', () => {
  it('fetchProducts populates list on success', async () => {
    mockGetProducts.mockResolvedValue({
      success: true,
      data: [{ id: 1, name: 'A' }],
      total: 1,
    });
    const store = useProductsStore();
    const result = await store.fetchProducts({ page: 1 });
    expect(result.success).toBe(true);
    expect(store.products).toHaveLength(1);
    expect(store.productCount).toBe(1);
    expect(store.loading).toBe(false);
  });

  it('fetchProducts sets error on failure response', async () => {
    mockGetProducts.mockResolvedValue({ success: false, message: 'bad' });
    const store = useProductsStore();
    const result = await store.fetchProducts();
    expect(result.success).toBe(false);
    expect(store.error).toBe('bad');
  });

  it('fetchProducts handles thrown error', async () => {
    mockGetProducts.mockRejectedValue(new Error('network'));
    const store = useProductsStore();
    const result = await store.fetchProducts();
    expect(result.success).toBe(false);
    expect(store.error).toBe('network');
  });

  it('deleteProduct removes local item', async () => {
    mockDeleteProduct.mockResolvedValue({ success: true });
    const store = useProductsStore();
    store.products = [{ id: 5, name: 'X' } as never];
    const result = await store.deleteProduct(5);
    expect(result.success).toBe(true);
    expect(store.products).toHaveLength(0);
  });

  it('batchDelete filters ids', async () => {
    mockBatchDelete.mockResolvedValue({ success: true });
    const store = useProductsStore();
    store.products = [
      { id: 1, name: 'A' } as never,
      { id: 2, name: 'B' } as never,
    ];
    await store.batchDelete([1]);
    expect(store.products.map((p) => p.id)).toEqual([2]);
  });

  it('createProduct refetches on success', async () => {
    mockCreateProduct.mockResolvedValue({ success: true });
    mockGetProducts.mockResolvedValue({ success: true, data: [], total: 0 });
    const store = useProductsStore();
    const result = await store.createProduct({ name: 'N' } as never);
    expect(result.success).toBe(true);
    expect(mockGetProducts).toHaveBeenCalled();
  });
});
