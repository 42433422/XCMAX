import { describe, it, expect } from 'vitest'
import {
  BUTLER_VIRTUAL_AREA_ID,
  BUTLER_VIRTUAL_EMPLOYEE_ID,
  BUTLER_PROFILE,
  describeHandler,
  extractEmployeeCapabilityView,
  butlerCapabilityView,
} from './butlerEmployeeProfile'

describe('butlerEmployeeProfile', () => {
  it('exports butler constants', () => {
    expect(BUTLER_VIRTUAL_AREA_ID).toBe('ai-butler')
    expect(BUTLER_VIRTUAL_EMPLOYEE_ID).toBeTruthy()
    expect(BUTLER_PROFILE.name).toBeTruthy()
  })

  it('describeHandler returns label for known handler', () => {
    const label = describeHandler('butler_skill')
    expect(typeof label).toBe('string')
    expect(label.length).toBeGreaterThan(0)
  })

  it('describeHandler returns handler name for unknown', () => {
    expect(describeHandler('__unknown_handler__')).toBe('__unknown_handler__')
  })

  it('extractEmployeeCapabilityView maps v2 manifest skills', () => {
    const view = extractEmployeeCapabilityView({
      employee_config_v2: {
        cognition: {
          skills: [{ name: '技能1', brief: '说明' }],
        },
      },
    })
    expect(view.skills).toHaveLength(1)
    expect(view.skills[0].name).toBe('技能1')
  })

  it('butlerCapabilityView returns virtual butler profile', () => {
    const view = butlerCapabilityView()
    expect(view.virtual).toBe(true)
    expect(view.skills.length).toBeGreaterThan(0)
  })
})
