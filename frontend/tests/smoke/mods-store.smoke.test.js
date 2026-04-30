/**
 * 前端冒烟：Mod 列表 Pinia 商店（不启 dev server，mock fetch）
 *
 * 单次：npm run test:smoke
 * 热重跑（改测试或 src/stores/mods 即重跑）：npm run test:smoke:watch
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useModsStore } from '@/stores/mods'

describe('mods store smoke', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn())
  })

  it('initialize 成功后写入 mods 并标记 isLoaded', async () => {
    // initialize：fetchModsWithRetry → GET /api/mods/，再 fetchModRoutes → GET /api/mods/routes（apiFetch → fetch）
    global.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          data: [
            {
              id: 'example-mod',
              name: 'Example Mod',
              version: '1.0.0',
              author: '',
              description: '',
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          data: [{ mod_id: 'example-mod', routes_path: 'mods/example-mod/frontend/routes' }],
        }),
      })

    const store = useModsStore()
    await store.initialize()

    expect(store.isLoaded).toBe(true)
    expect(store.mods.length).toBe(1)
    expect(store.mods[0].id).toBe('example-mod')
  })
})
