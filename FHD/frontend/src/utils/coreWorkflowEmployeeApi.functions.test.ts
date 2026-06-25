import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockApiFetch, mockIsWorkflowEmployeeId, mockFindWorkflowEmployeeEntry } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  mockIsWorkflowEmployeeId: vi.fn(),
  mockFindWorkflowEmployeeEntry: vi.fn(),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: mockApiFetch,
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))

vi.mock('@/constants/workflowEmployeeMods', () => ({
  isWorkflowEmployeeId: mockIsWorkflowEmployeeId,
}))

vi.mock('@/utils/modWorkflowEmployees', () => ({
  findWorkflowEmployeeEntry: mockFindWorkflowEmployeeEntry,
}))

import {
  postCoreWorkflowEmployeeRun,
  tryPostCoreWorkflowEmployeeRun,
} from './coreWorkflowEmployeeApi'

describe('coreWorkflowEmployeeApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('postCoreWorkflowEmployeeRun', () => {
    it('throws when mod not installed (no mods provided)', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue(null)
      await expect(
        postCoreWorkflowEmployeeRun('label_print' as never, { action: 'status' }, []),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
      expect(mockApiFetch).not.toHaveBeenCalled()
    })

    it('throws when mod not installed (undefined mods)', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue(null)
      await expect(
        postCoreWorkflowEmployeeRun('label_print' as never, { action: 'status' }, undefined),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('throws when findWorkflowEmployeeEntry returns null entry', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue(null)
      await expect(
        postCoreWorkflowEmployeeRun('shipment_mgmt' as never, { action: 'run' }, [
          { id: 'other-mod', workflow_employees: [{ id: 'other_emp' }] },
        ]),
      ).rejects.toThrow('workflow employee mod not installed: shipment_mgmt')
    })

    it('throws when modId is empty string', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'label_print', modId: '', modName: '' })
      await expect(
        postCoreWorkflowEmployeeRun('label_print' as never, { action: 'status' }, []),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('throws when modId is whitespace only', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({
        id: 'label_print',
        modId: '   ',
        modName: '',
      })
      await expect(
        postCoreWorkflowEmployeeRun('label_print' as never, { action: 'status' }, []),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('calls apiFetch with correct path when mod installed', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({
        id: 'label_print',
        modId: 'xcagi-workflow-employee-label-print',
        modName: 'Label Print',
      })
      const mockResponse = {
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: { ok: true } }),
      }
      mockApiFetch.mockResolvedValue(mockResponse)
      const result = await postCoreWorkflowEmployeeRun(
        'label_print' as never,
        { action: 'status' },
        [],
      )
      expect(mockApiFetch).toHaveBeenCalledTimes(1)
      const [path, init] = mockApiFetch.mock.calls[0]
      expect(path).toBe(
        '/api/mod/xcagi-workflow-employee-label-print/employees/label_print/run',
      )
      expect(init.method).toBe('POST')
      expect(init.headers['Content-Type']).toBe('application/json')
      expect(init.body).toBe(JSON.stringify({ action: 'status' }))
      expect(init.timeoutMs).toBe(90_000)
      expect(result).toEqual({ success: true, data: { ok: true } })
    })

    it('URL-encodes employeeId in path', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({
        id: 'wechat/phone',
        modId: 'mod-1',
        modName: 'Mod 1',
      })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      })
      await postCoreWorkflowEmployeeRun('wechat/phone' as never, { action: 'x' }, [])
      const [path] = mockApiFetch.mock.calls[0]
      expect(path).toBe('/api/mod/mod-1/employees/wechat%2Fphone/run')
    })

    it('uses default payload when none provided', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
      await postCoreWorkflowEmployeeRun('e1' as never)
      const [, init] = mockApiFetch.mock.calls[0]
      expect(init.body).toBe(JSON.stringify({ action: 'status' }))
    })

    it('throws when HTTP response not ok', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({ ok: false, status: 500 })
      await expect(
        postCoreWorkflowEmployeeRun('e1' as never, { action: 'status' }, []),
      ).rejects.toThrow('workflow employee run e1: HTTP 500')
    })

    it('throws on 404 response', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({ ok: false, status: 404 })
      await expect(
        postCoreWorkflowEmployeeRun('e1' as never, { action: 'status' }, []),
      ).rejects.toThrow('workflow employee run e1: HTTP 404')
    })

    it('passes through custom payload with extra fields', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: { ok: true, summary: 'done' } }),
      })
      const payload = { action: 'custom', foo: 'bar', count: 42 }
      const result = await postCoreWorkflowEmployeeRun('e1' as never, payload, [])
      const [, init] = mockApiFetch.mock.calls[0]
      expect(init.body).toBe(JSON.stringify(payload))
      expect(result).toEqual({ success: true, data: { ok: true, summary: 'done' } })
    })

    it('trims modId when building path', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({
        id: 'e1',
        modId: '  m1  ',
        modName: '',
      })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
      await postCoreWorkflowEmployeeRun('e1' as never, { action: 'status' }, [])
      const [path] = mockApiFetch.mock.calls[0]
      expect(path).toBe('/api/mod/m1/employees/e1/run')
    })

    it('propagates apiFetch network errors', async () => {
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockRejectedValue(new TypeError('Failed to fetch'))
      await expect(
        postCoreWorkflowEmployeeRun('e1' as never, { action: 'status' }, []),
      ).rejects.toThrow('Failed to fetch')
    })
  })

  describe('tryPostCoreWorkflowEmployeeRun', () => {
    it('returns null when employeeId is not a valid workflow employee id', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(false)
      const result = await tryPostCoreWorkflowEmployeeRun('invalid_id', { action: 'status' }, [])
      expect(result).toBeNull()
      expect(mockApiFetch).not.toHaveBeenCalled()
      expect(mockFindWorkflowEmployeeEntry).not.toHaveBeenCalled()
    })

    it('returns null for empty string employeeId', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(false)
      const result = await tryPostCoreWorkflowEmployeeRun('', { action: 'status' }, [])
      expect(result).toBeNull()
    })

    it('returns success response when postCoreWorkflowEmployeeRun succeeds', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, data: { ok: true, summary: 'ok' } }),
      })
      const result = await tryPostCoreWorkflowEmployeeRun('e1', { action: 'status' }, [])
      expect(result).toEqual({ success: true, data: { ok: true, summary: 'ok' } })
    })

    it('returns failure object when postCoreWorkflowEmployeeRun throws (mod not installed)', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue(null)
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const result = await tryPostCoreWorkflowEmployeeRun('e1', { action: 'status' }, [])
      expect(result).toEqual({ success: false, data: { ok: false } })
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
    })

    it('returns failure object when HTTP response not ok', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({ ok: false, status: 500 })
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const result = await tryPostCoreWorkflowEmployeeRun('e1', { action: 'status' }, [])
      expect(result).toEqual({ success: false, data: { ok: false } })
      warnSpy.mockRestore()
    })

    it('returns failure object on network error', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockRejectedValue(new TypeError('Failed to fetch'))
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const result = await tryPostCoreWorkflowEmployeeRun('e1', { action: 'status' }, [])
      expect(result).toEqual({ success: false, data: { ok: false } })
      warnSpy.mockRestore()
    })

    it('uses default payload when none provided', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue({ id: 'e1', modId: 'm1', modName: '' })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      })
      await tryPostCoreWorkflowEmployeeRun('e1')
      const [, init] = mockApiFetch.mock.calls[0]
      expect(init.body).toBe(JSON.stringify({ action: 'status' }))
    })

    it('passes mods parameter through to postCoreWorkflowEmployeeRun', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      const mods = [{ id: 'm1', workflow_employees: [{ id: 'e1' }] }]
      mockFindWorkflowEmployeeEntry.mockImplementation((m: unknown, id: string) => {
        if (id === 'e1') return { id: 'e1', modId: 'm1', modName: '' }
        return null
      })
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      })
      await tryPostCoreWorkflowEmployeeRun('e1', { action: 'status' }, mods)
      expect(mockFindWorkflowEmployeeEntry).toHaveBeenCalledWith(mods, 'e1')
    })

    it('logs warning with employeeId and error on failure', async () => {
      mockIsWorkflowEmployeeId.mockReturnValue(true)
      mockFindWorkflowEmployeeEntry.mockReturnValue(null)
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      await tryPostCoreWorkflowEmployeeRun('special_emp', { action: 'status' }, [])
      expect(warnSpy).toHaveBeenCalledWith(
        '[coreWorkflowEmployeeApi]',
        'special_emp',
        expect.any(Error),
      )
      warnSpy.mockRestore()
    })
  })
})
