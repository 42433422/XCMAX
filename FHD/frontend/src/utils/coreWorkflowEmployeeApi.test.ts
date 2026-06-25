import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))

import {
  postCoreWorkflowEmployeeRun,
  tryPostCoreWorkflowEmployeeRun,
} from './coreWorkflowEmployeeApi'

describe('coreWorkflowEmployeeApi', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  describe('postCoreWorkflowEmployeeRun', () => {
    it('throws when mod not found for employee', async () => {
      await expect(
        postCoreWorkflowEmployeeRun('label_print', { action: 'status' }, []),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('throws when mods is undefined', async () => {
      await expect(
        postCoreWorkflowEmployeeRun('label_print', { action: 'status' }, undefined),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('posts to correct endpoint when mod found', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { ok: true, summary: 'done' } }),
      })
      const mods = [
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: '标签打印' }],
        },
      ]
      const result = await postCoreWorkflowEmployeeRun(
        'label_print',
        { action: 'run' },
        mods,
      )
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mod/xcagi-workflow-employee-label-print/employees/label_print/run',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'run' }),
          timeoutMs: 90_000,
        }),
      )
      expect(result.success).toBe(true)
      expect(result.data?.ok).toBe(true)
      expect(result.data?.summary).toBe('done')
    })

    it('uses default payload when not specified', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true }),
      })
      const mods = [
        {
          id: 'xcagi-workflow-employee-shipment-mgmt',
          workflow_employees: [{ id: 'shipment_mgmt', label: '发货管理' }],
        },
      ]
      await postCoreWorkflowEmployeeRun('shipment_mgmt', undefined, mods)
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({ action: 'status' }),
        }),
      )
    })

    it('encodes employee_id in URL', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true }),
      })
      const mods = [
        {
          id: 'mod-with-special-chars',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      await postCoreWorkflowEmployeeRun('label_print', {}, mods)
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mod/mod-with-special-chars/employees/label_print/run',
        expect.any(Object),
      )
    })

    it('throws when response is not ok', async () => {
      apiFetchMock.mockResolvedValue({ ok: false, status: 500 })
      const mods = [
        {
          id: 'mod-1',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      await expect(
        postCoreWorkflowEmployeeRun('label_print', {}, mods),
      ).rejects.toThrow('workflow employee run label_print: HTTP 500')
    })

    it('throws on 404 response', async () => {
      apiFetchMock.mockResolvedValue({ ok: false, status: 404 })
      const mods = [
        {
          id: 'mod-1',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      await expect(
        postCoreWorkflowEmployeeRun('label_print', {}, mods),
      ).rejects.toThrow('workflow employee run label_print: HTTP 404')
    })

    it('handles mod with empty id', async () => {
      const mods = [
        {
          id: '',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      // modId is empty string → trim() returns '' → falsy → throws
      await expect(
        postCoreWorkflowEmployeeRun('label_print', {}, mods),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })

    it('handles mod with whitespace id', async () => {
      const mods = [
        {
          id: '   ',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      await expect(
        postCoreWorkflowEmployeeRun('label_print', {}, mods),
      ).rejects.toThrow('workflow employee mod not installed: label_print')
    })
  })

  describe('tryPostCoreWorkflowEmployeeRun', () => {
    it('returns null when employeeId is not a workflow employee id', async () => {
      const result = await tryPostCoreWorkflowEmployeeRun('not-a-valid-id', {}, [])
      expect(result).toBeNull()
      expect(apiFetchMock).not.toHaveBeenCalled()
    })

    it('returns null for empty string', async () => {
      const result = await tryPostCoreWorkflowEmployeeRun('', {}, [])
      expect(result).toBeNull()
    })

    it('returns success result when API succeeds', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, data: { ok: true } }),
      })
      const mods = [
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      const result = await tryPostCoreWorkflowEmployeeRun('label_print', {}, mods)
      expect(result).not.toBeNull()
      expect(result?.success).toBe(true)
    })

    it('returns failure result when mod not installed', async () => {
      const result = await tryPostCoreWorkflowEmployeeRun('label_print', {}, [])
      expect(result).toEqual({ success: false, data: { ok: false } })
    })

    it('returns failure result when API throws', async () => {
      apiFetchMock.mockResolvedValue({ ok: false, status: 500 })
      const mods = [
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      const result = await tryPostCoreWorkflowEmployeeRun('label_print', {}, mods)
      expect(result).toEqual({ success: false, data: { ok: false } })
    })

    it('returns failure result when fetch rejects', async () => {
      apiFetchMock.mockRejectedValue(new Error('network'))
      const mods = [
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      const result = await tryPostCoreWorkflowEmployeeRun('label_print', {}, mods)
      expect(result).toEqual({ success: false, data: { ok: false } })
    })

    it('uses default payload when not specified', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true }),
      })
      const mods = [
        {
          id: 'xcagi-workflow-employee-label-print',
          workflow_employees: [{ id: 'label_print', label: 'L' }],
        },
      ]
      await tryPostCoreWorkflowEmployeeRun('label_print', undefined, mods)
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({ action: 'status' }),
        }),
      )
    })
  })
})
