import { describe, it, expect, beforeEach, vi } from 'vitest'

const requestJsonMock = vi.fn()

vi.mock('../infrastructure/http/client', () => ({
  requestJson: requestJsonMock,
}))

describe('hostConfig', () => {
  beforeEach(() => {
    vi.resetModules()
    requestJsonMock.mockReset()
  })

  it('bootstrapHostConfig loads presets and rules', async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        data: {
          preset_ids: ['p1', 'p2'],
          presets: {
            p1: { id: 'p1', name: 'Preset 1' },
            p2: { id: 'p2', name: 'Preset 2' },
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          workflow_employee_id_prefixes: ['WF-'],
          exclude_id_suffixes: ['-test'],
        },
      })

    const { bootstrapHostConfig, industryPresets, industryPresetIds, employeeRegistryRules } =
      await import('./hostConfig')

    await bootstrapHostConfig()

    expect(industryPresets.value).toHaveProperty('p1')
    expect(industryPresets.value).toHaveProperty('p2')
    expect(industryPresetIds.value).toEqual(['p1', 'p2'])
    expect(employeeRegistryRules.value).not.toBeNull()
    expect(employeeRegistryRules.value?.workflow_employee_id_prefixes).toEqual(['WF-'])
  })

  it('bootstrapHostConfig derives preset ids from keys when preset_ids missing', async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        data: {
          presets: {
            a: { id: 'a', name: 'A' },
            b: { id: 'b', name: 'B' },
          },
        },
      })
      .mockResolvedValueOnce(null)

    const { bootstrapHostConfig, industryPresetIds, employeeRegistryRules } = await import(
      './hostConfig'
    )

    await bootstrapHostConfig()

    expect(industryPresetIds.value).toEqual(['a', 'b'])
    expect(employeeRegistryRules.value).toBeNull()
  })

  it('bootstrapHostConfig handles unwrapped response (no data envelope)', async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        presets: { x: { id: 'x', name: 'X' } },
      })
      .mockResolvedValueOnce({
        workflow_employee_id_prefixes: ['X-'],
      })

    const { bootstrapHostConfig, industryPresets, employeeRegistryRules } = await import(
      './hostConfig'
    )

    await bootstrapHostConfig()

    expect(industryPresets.value).toHaveProperty('x')
    expect(employeeRegistryRules.value?.workflow_employee_id_prefixes).toEqual(['X-'])
  })

  it('bootstrapHostConfig is idempotent (loaded flag)', async () => {
    requestJsonMock
      .mockResolvedValueOnce({ data: { presets: { p1: { id: 'p1' } } } })
      .mockResolvedValueOnce({ data: { workflow_employee_id_prefixes: [] } })

    const { bootstrapHostConfig, industryPresetIds } = await import('./hostConfig')

    await bootstrapHostConfig()
    expect(industryPresetIds.value).toEqual(['p1'])

    requestJsonMock.mockClear()
    await bootstrapHostConfig()
    expect(requestJsonMock).not.toHaveBeenCalled()
  })

  it('bootstrapHostConfig handles request failures gracefully', async () => {
    requestJsonMock
      .mockRejectedValueOnce(new Error('network'))
      .mockRejectedValueOnce(new Error('network'))

    const { bootstrapHostConfig, industryPresets, employeeRegistryRules } = await import(
      './hostConfig'
    )

    await expect(bootstrapHostConfig()).resolves.not.toThrow()
    expect(Object.keys(industryPresets.value)).toHaveLength(0)
    expect(employeeRegistryRules.value).toBeNull()
  })

  it('bootstrapHostConfig handles null responses', async () => {
    requestJsonMock.mockResolvedValueOnce(null).mockResolvedValueOnce(null)

    const { bootstrapHostConfig, industryPresets, employeeRegistryRules } = await import(
      './hostConfig'
    )

    await bootstrapHostConfig()
    expect(Object.keys(industryPresets.value)).toHaveLength(0)
    expect(employeeRegistryRules.value).toBeNull()
  })

  it('bootstrapHostConfig handles non-array preset_ids', async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        data: {
          preset_ids: 'not-an-array',
          presets: { k: { id: 'k' } },
        },
      })
      .mockResolvedValueOnce(null)

    const { bootstrapHostConfig, industryPresetIds } = await import('./hostConfig')

    await bootstrapHostConfig()
    expect(industryPresetIds.value).toEqual(['k'])
  })

  it('bootstrapHostConfig handles empty presets object', async () => {
    requestJsonMock
      .mockResolvedValueOnce({ data: { presets: {} } })
      .mockResolvedValueOnce(null)

    const { bootstrapHostConfig, industryPresets, industryPresetIds } = await import('./hostConfig')

    await bootstrapHostConfig()
    expect(Object.keys(industryPresets.value)).toHaveLength(0)
    expect(industryPresetIds.value).toEqual([])
  })
})
