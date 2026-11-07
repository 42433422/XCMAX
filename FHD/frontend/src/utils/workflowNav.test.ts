import { describe, expect, it, afterEach } from 'vitest'
import { resolveWorkflowVisualizationLocation, workflowVisualizationModPath } from './workflowNav'

const CORE_LS = 'xcagi_workflow_viz_mod_pages_enabled'

describe('workflowNav', () => {
  afterEach(() => {
    localStorage.removeItem(CORE_LS)
  })

  it('uses host route names when mod facades off', () => {
    expect(resolveWorkflowVisualizationLocation()).toEqual({ name: 'workflow-visualization' })
  })

  it('uses mod paths when facades on', () => {
    localStorage.setItem(CORE_LS, '1')
    expect(resolveWorkflowVisualizationLocation()).toEqual({
      path: workflowVisualizationModPath(),
    })
  })
})
