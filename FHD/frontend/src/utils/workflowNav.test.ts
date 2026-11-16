import { describe, expect, it, afterEach, vi } from 'vitest'
import { resolveWorkflowVisualizationLocation, workflowVisualizationModPath } from './workflowNav'

const CORE_LS = 'xcagi_workflow_viz_mod_pages_enabled'

describe('workflowNav', () => {
  afterEach(() => {
    localStorage.removeItem(CORE_LS)
    vi.unstubAllEnvs()
  })

  it('uses host route names in admin console builds', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    expect(resolveWorkflowVisualizationLocation()).toEqual({ name: 'workflow-visualization' })
  })

  it('falls back to a plain path when the host route is not registered', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    expect(resolveWorkflowVisualizationLocation()).toEqual({
      path: workflowVisualizationModPath(),
    })
  })

  it('uses mod paths when facades on', () => {
    localStorage.setItem(CORE_LS, '1')
    expect(resolveWorkflowVisualizationLocation()).toEqual({
      path: workflowVisualizationModPath(),
    })
  })
})
