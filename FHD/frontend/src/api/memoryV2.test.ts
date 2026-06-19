import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryV2Api } from './memoryV2';

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
    patch: vi.fn().mockResolvedValue({ success: true }),
    delete: vi.fn().mockResolvedValue({ success: true }),
  },
}));

describe('memoryV2Api', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists memory records with filters', async () => {
    await memoryV2Api.list({ userId: 'u1', status: 'active', memoryType: 'preference' });
    const { api } = await import('./core');
    expect(api.get).toHaveBeenCalledWith('/api/memory/v2', {
      user_id: 'u1',
      status: 'active',
      memory_type: 'preference',
    });
  });

  it('loads summary for default user', async () => {
    await memoryV2Api.summary();
    const { api } = await import('./core');
    expect(api.get).toHaveBeenCalledWith('/api/memory/v2/summary', {
      user_id: 'default',
    });
  });

  it('creates a candidate with normalized payload keys', async () => {
    await memoryV2Api.createCandidate({
      userId: 'u2',
      memoryType: 'entity',
      key: 'customer',
      value: '七彩乐园',
      confidence: 0.8,
      source: 'settings_ui',
    });
    const { api } = await import('./core');
    expect(api.post).toHaveBeenCalledWith('/api/memory/v2/candidates', {
      user_id: 'u2',
      memory_type: 'entity',
      key: 'customer',
      value: '七彩乐园',
      confidence: 0.8,
      source: 'settings_ui',
      evidence: undefined,
    });
  });

  it('confirms and rejects memory records', async () => {
    await memoryV2Api.confirm('mem/1', 'u3', { value: '确认值' });
    await memoryV2Api.reject('mem/1', 'u3', '误识别');
    const { api } = await import('./core');
    expect(api.post).toHaveBeenNthCalledWith(1, '/api/memory/v2/mem%2F1/confirm', {
      user_id: 'u3',
      correction: { value: '确认值' },
    });
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/memory/v2/mem%2F1/reject', {
      user_id: 'u3',
      reason: '误识别',
    });
  });

  it('corrects and deletes memory records', async () => {
    await memoryV2Api.correct('mem/2', {
      userId: 'u4',
      key: 'favorite_customer',
      value: '彩虹乐园',
      reason: 'settings_ui_correction',
    });
    await memoryV2Api.remove('mem/2', 'u4', '用户删除');
    const { api } = await import('./core');
    expect(api.patch).toHaveBeenCalledWith('/api/memory/v2/mem%2F2', {
      user_id: 'u4',
      key: 'favorite_customer',
      value: '彩虹乐园',
      reason: 'settings_ui_correction',
    });
    expect(api.delete).toHaveBeenCalledWith('/api/memory/v2/mem%2F2?user_id=u4&reason=%E7%94%A8%E6%88%B7%E5%88%A0%E9%99%A4');
  });
});
