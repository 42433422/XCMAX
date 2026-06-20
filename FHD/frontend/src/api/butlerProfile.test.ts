import { describe, it, expect, vi, beforeEach } from 'vitest';
import { butlerProfileApi } from './butlerProfile';

// Mock api core
vi.mock('./core', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from './core';

describe('butlerProfileApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('get', () => {
    it('calls GET /api/butler/profile with user_id param', async () => {
      vi.mocked(api.get).mockResolvedValue({ success: true, profile: { user_id: 1 } });
      await butlerProfileApi.get(42);
      expect(api.get).toHaveBeenCalledWith('/api/butler/profile', { user_id: 42 });
    });

    it('defaults user_id to 1 when not provided', async () => {
      vi.mocked(api.get).mockResolvedValue({ success: true });
      await butlerProfileApi.get();
      expect(api.get).toHaveBeenCalledWith('/api/butler/profile', { user_id: 1 });
    });

    it('defaults user_id to 1 when 0 provided', async () => {
      vi.mocked(api.get).mockResolvedValue({ success: true });
      await butlerProfileApi.get(0);
      expect(api.get).toHaveBeenCalledWith('/api/butler/profile', { user_id: 1 });
    });
  });

  describe('infer', () => {
    it('calls POST /api/butler/profile/infer with conversations and mod_hints', async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      await butlerProfileApi.infer({
        userId: 5,
        conversations: [{ user_message: 'hi', assistant_message: 'hello' }],
        mod_hints: ['考勤'],
      });
      expect(api.post).toHaveBeenCalledWith('/api/butler/profile/infer', {
        user_id: 5,
        conversations: [{ user_message: 'hi', assistant_message: 'hello' }],
        mod_hints: ['考勤'],
      });
    });

    it('defaults empty arrays when not provided', async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      await butlerProfileApi.infer({});
      expect(api.post).toHaveBeenCalledWith('/api/butler/profile/infer', {
        user_id: 1,
        conversations: [],
        mod_hints: [],
      });
    });
  });

  describe('recordInteraction', () => {
    it('calls POST /api/butler/profile/interaction with correct payload', async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      await butlerProfileApi.recordInteraction({
        userId: 3,
        userMessage: '帮我查考勤',
        assistantMessage: '好的，正在查询',
        interrupted: false,
        corrected: true,
      });
      expect(api.post).toHaveBeenCalledWith('/api/butler/profile/interaction', {
        user_id: 3,
        user_message: '帮我查考勤',
        assistant_message: '好的，正在查询',
        interrupted: false,
        corrected: true,
      });
    });

    it('defaults interrupted and corrected to false', async () => {
      vi.mocked(api.post).mockResolvedValue({ success: true });
      await butlerProfileApi.recordInteraction({
        userMessage: 'hi',
        assistantMessage: 'hello',
      });
      expect(api.post).toHaveBeenCalledWith('/api/butler/profile/interaction', {
        user_id: 1,
        user_message: 'hi',
        assistant_message: 'hello',
        interrupted: false,
        corrected: false,
      });
    });
  });
});
