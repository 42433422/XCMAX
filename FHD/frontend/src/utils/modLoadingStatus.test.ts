import { describe, expect, it } from 'vitest'
import { summarizeModLoadingData } from './modLoadingStatus'

describe('modLoadingStatus', () => {
  it('returns null for empty input', () => {
    expect(summarizeModLoadingData(null)).toBeNull()
    expect(summarizeModLoadingData(undefined)).toBeNull()
  })

  it('reports mods disabled', () => {
    const s = summarizeModLoadingData({ mods_disabled: true })
    expect(s).toContain('XCAGI_DISABLE_MODS')
  })

  it('reports load mismatch', () => {
    const s = summarizeModLoadingData({ load_mismatch: true })
    expect(s).toContain('未载入')
  })

  it('includes first load error', () => {
    const s = summarizeModLoadingData({
      load_errors: [{ mod_id: 'm1', stage: 'init', message: 'fail' }],
    })
    expect(s).toContain('m1')
    expect(s).toContain('fail')
  })

  it('partial failure fallback', () => {
    const s = summarizeModLoadingData({ partial_failure: true })
    expect(s).toContain('部分 Mod')
  })
})
