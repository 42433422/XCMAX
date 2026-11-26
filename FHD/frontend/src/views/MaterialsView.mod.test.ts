import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getMock, postMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), postMock: vi.fn(), putMock: vi.fn() }))
vi.mock('@/api', () => ({ get: getMock, post: postMock, api: { put: putMock, delete: vi.fn() } }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn(), appConfirm: vi.fn() }))

import MaterialsView from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/MaterialsView.vue'

describe('ERP materials page contract', () => {
  let wrapper: ReturnType<typeof mount> | undefined
  beforeEach(() => {
    vi.clearAllMocks()
    getMock.mockImplementation((path: string, params?: { page?: number }) => Promise.resolve(
      path === '/api/materials'
        ? { success: true, total: 120, data: [{ id: params?.page || 1, name: '物料页 ' + (params?.page || 1) }] }
        : { success: true, total: 0, data: [] },
    ))
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers() })
  function open() {
    wrapper = mount(MaterialsView, { global: { plugins: [createPinia()] } })
    return wrapper
  }

  it('uses actual server pagination instead of truncating to the first material page', async () => {
    const page = open()
    await flushPromises()
    expect(getMock).toHaveBeenCalledWith('/api/materials', { page: 1, per_page: 50 }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(page.get('nav[aria-label="服务端分页"]').text()).toContain('1 / 3 · 共 120 条')
    await page.get('nav[aria-label="服务端分页"] button:last-child').trigger('click')
    await flushPromises()
    expect(getMock).toHaveBeenCalledWith('/api/materials', { page: 2, per_page: 50 }, expect.anything())
    expect(page.text()).toContain('物料页 2')
    expect(page.text()).not.toContain('物料页 1')
  })

  it('aborts and retires a previous query before the debounced search starts', async () => {
    vi.useFakeTimers()
    let resolveOld!: (value: unknown) => void
    let oldSignal: AbortSignal | undefined
    getMock.mockImplementation((path: string, params?: { search?: string }, options?: { signal?: AbortSignal }) => {
      if (path !== '/api/materials') return Promise.resolve({ success: true, data: [], total: 0 })
      if (params?.search) return Promise.resolve({ success: true, total: 1, data: [{ id: 2, name: '新搜索结果' }] })
      oldSignal = options?.signal
      return new Promise(resolve => { resolveOld = resolve })
    })
    const page = open()
    await page.get('.search-box input').setValue('新')
    expect(oldSignal?.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(280)
    await flushPromises()
    resolveOld({ success: true, total: 1, data: [{ id: 1, name: '旧搜索结果' }] })
    await flushPromises()
    expect(page.text()).toContain('新搜索结果')
    expect(page.text()).not.toContain('旧搜索结果')
  })

  it('distinguishes a permission failure from an empty result', async () => {
    getMock.mockImplementation((path: string) => path === '/api/materials'
      ? Promise.reject(Object.assign(new Error('Forbidden'), { status: 403 }))
      : Promise.resolve({ success: true, data: [] }))
    const page = open()
    await flushPromises()
    expect(page.get('[role="alert"]').text()).toContain('无权限读取数据')
    expect(page.text()).not.toContain('暂无数据')
  })

  it('saves an existing supplier using only editable fields', async () => {
    getMock.mockImplementation((path: string) => Promise.resolve({
      success: true,
      data: path === '/api/purchase/suppliers' ? [{
        id: 7, code: 'SUP-7', name: '原供应商', contact_person: '原联系人',
        contact_phone: '100', rating: 3, tenant_id: 12, created_at: '2026-11-25',
      }] : [],
      total: 0,
    }))
    putMock.mockResolvedValue({ success: true })
    const page = open()
    await page.get('.tabs button:last-child').trigger('click')
    await flushPromises()
    await page.get('.card button.btn-secondary').trigger('click')
    const fields = page.findAll('.modal input')
    expect(fields[0].attributes('disabled')).toBeDefined()
    await fields[2].setValue('新联系人')
    await page.get('.modal .modal-footer .btn-primary').trigger('click')
    await flushPromises()
    expect(putMock).toHaveBeenCalledExactlyOnceWith('/api/purchase/suppliers/7', {
      name: '原供应商', contact_person: '新联系人', contact_phone: '100', rating: 3,
    })
    expect(page.find('.modal').exists()).toBe(false)
  })
})
