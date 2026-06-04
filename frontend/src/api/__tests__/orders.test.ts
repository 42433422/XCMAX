import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockGet = vi.fn();
const mockDelete = vi.fn();
const mockPost = vi.fn();

vi.mock('@/api/index', () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    delete: (...args: any[]) => mockDelete(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

import { ordersApi } from '@/api/orders';

beforeEach(() => {
  mockGet.mockReset();
  mockDelete.mockReset();
  mockPost.mockReset();
});

describe('ordersApi.getOrders', () => {
  it('should call GET /api/orders', async () => {
    mockGet.mockResolvedValueOnce({ success: true, data: [] });
    const result = await ordersApi.getOrders();
    expect(mockGet).toHaveBeenCalledWith('/api/orders', {});
    expect(result.success).toBe(true);
  });
});

describe('ordersApi.getOrder', () => {
  it('should call GET /api/orders/:id with encoded id', async () => {
    mockGet.mockResolvedValueOnce({ success: true, data: {} });
    await ordersApi.getOrder('ORD-001');
    expect(mockGet).toHaveBeenCalledWith('/api/orders/ORD-001');
  });
});

describe('ordersApi.searchOrders', () => {
  it('should call GET /api/orders/search with query', async () => {
    mockGet.mockResolvedValueOnce({ success: true, data: [] });
    await ordersApi.searchOrders('test query');
    expect(mockGet).toHaveBeenCalledWith('/api/orders/search', { q: 'test query' });
  });
});

describe('ordersApi.deleteOrder', () => {
  it('should call DELETE /api/shipment/orders/:id', async () => {
    mockDelete.mockResolvedValueOnce({ success: true });
    await ordersApi.deleteOrder('ORD-001');
    expect(mockDelete).toHaveBeenCalledWith('/api/shipment/orders/ORD-001');
  });
});
