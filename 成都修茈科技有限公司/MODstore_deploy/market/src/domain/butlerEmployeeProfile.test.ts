import { describe, expect, it } from 'vitest'
import {
  BUTLER_VIRTUAL_EMPLOYEE_ID,
  BUTLER_PROFILE,
  describeHandler,
  extractEmployeeCapabilityView,
  butlerCapabilityView,
} from './butlerEmployeeProfile'

describe('describeHandler', () => {
  it('returns friendly label for known handlers', () => {
    expect(describeHandler('echo')).toContain('复述')
    expect(describeHandler('webhook')).toContain('Webhook')
    expect(describeHandler('llm_md')).toContain('Markdown')
    expect(describeHandler('butler_chat')).toContain('/api/agent/butler/chat')
  })

  it('returns handler name for unknown handlers', () => {
    expect(describeHandler('custom_handler')).toBe('custom_handler')
  })
})

describe('extractEmployeeCapabilityView', () => {
  it('returns empty view for null manifest', () => {
    const view = extractEmployeeCapabilityView(null)
    expect(view.persona).toBe('')
    expect(view.skills).toEqual([])
    expect(view.handlers).toEqual([])
    expect(view.virtual).toBe(false)
  })

  it('returns empty view for undefined manifest', () => {
    const view = extractEmployeeCapabilityView(undefined)
    expect(view.persona).toBe('')
  })

  it('extracts from V2 manifest with employee_config_v2', () => {
    const manifest = {
      employee_config_v2: {
        cognition: {
          agent: {
            system_prompt: 'You are a helper',
            role: {
              persona: 'Assistant',
              expertise: ['coding', 'writing'],
            },
          },
          skills: [
            { name: 'Code Review', brief: 'Reviews code', kind: 'review' },
            { name: '', brief: 'Empty name', kind: 'skip' },
          ],
        },
        actions: {
          handlers: ['llm_md', 'webhook'],
        },
        collaboration: {
          workflow: { workflow_id: 42 },
          depends_on: ['emp1'],
        },
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.persona).toBe('Assistant')
    expect(view.expertise).toEqual(['coding', 'writing'])
    expect(view.skills).toHaveLength(1)
    expect(view.skills[0].name).toBe('Code Review')
    expect(view.handlers).toEqual(['llm_md', 'webhook'])
    expect(view.workflowId).toBe(42)
    expect(view.dependsOn).toEqual(['emp1'])
  })

  it('falls back to top-level actions when V2 has no handlers', () => {
    const manifest = {
      actions: {
        handlers: ['echo'],
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.handlers).toEqual(['echo'])
  })

  it('uses system_prompt as persona fallback', () => {
    const manifest = {
      employee_config_v2: {
        cognition: {
          agent: {
            system_prompt: 'You are a bot',
          },
        },
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.persona).toBe('You are a bot')
  })

  it('handles skills with how field', () => {
    const manifest = {
      employee_config_v2: {
        cognition: {
          skills: [
            { name: 'Navigate', brief: 'Navigate pages', kind: 'action', how: 'vue-router push' },
          ],
        },
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.skills[0].how).toBe('vue-router push')
  })

  it('handles skills without how field', () => {
    const manifest = {
      employee_config_v2: {
        cognition: {
          skills: [
            { name: 'Navigate', brief: 'Navigate pages', kind: 'action' },
          ],
        },
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.skills[0].how).toBeUndefined()
  })

  it('uses top-level depends_on when V2 has none', () => {
    const manifest = {
      depends_on: ['emp2'],
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.dependsOn).toEqual(['emp2'])
  })

  it('skips non-object skills', () => {
    const manifest = {
      employee_config_v2: {
        cognition: {
          skills: ['string_skill', null, 42, { name: 'Valid', brief: 'ok', kind: 'test' }],
        },
      },
    }
    const view = extractEmployeeCapabilityView(manifest)
    expect(view.skills).toHaveLength(1)
    expect(view.skills[0].name).toBe('Valid')
  })
})

describe('butlerCapabilityView', () => {
  it('returns virtual capability view', () => {
    const view = butlerCapabilityView()
    expect(view.virtual).toBe(true)
    expect(view.skills.length).toBeGreaterThan(0)
    expect(view.handlers.length).toBeGreaterThan(0)
    expect(view.persona).toBeTruthy()
  })

  it('has expected butler handlers', () => {
    const view = butlerCapabilityView()
    expect(view.handlers).toContain('butler_chat')
    expect(view.handlers).toContain('butler_navigate')
  })
})

describe('BUTLER_PROFILE', () => {
  it('has correct id', () => {
    expect(BUTLER_PROFILE.id).toBe(BUTLER_VIRTUAL_EMPLOYEE_ID)
  })

  it('has employee_config_v2', () => {
    expect(BUTLER_PROFILE.manifest.employee_config_v2).toBeDefined()
  })
})
