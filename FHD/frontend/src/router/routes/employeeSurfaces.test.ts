import { describe, expect, it } from 'vitest'
import { CORE_MENU_ITEMS_BASE } from '@/constants/coreMenuCatalog'
import { SHELL_ROUTES } from './shell'

describe('employee surfaces stay independently reachable', () => {
  it('keeps workbench, workspace and graph as distinct navigation entries', () => {
    const parent = CORE_MENU_ITEMS_BASE.find((item) => item.key === 'employee-workflow')
    expect(parent?.children?.map((child) => child.key)).toEqual([
      'employee-workbench',
      'workflow-employee-space',
      'workflow-employee-stitch-full',
    ])
  })

  it('binds the task workbench and desk workspace to separate components', () => {
    const workbench = SHELL_ROUTES.find((route) => route.name === 'employee-workbench')
    const workspace = SHELL_ROUTES.find((route) => route.name === 'workflow-employee-space')
    const graph = SHELL_ROUTES.find((route) => route.name === 'workflow-employee-stitch-full')
    expect(workbench?.path).toBe('/employee-workbench')
    expect(workspace?.path).toBe('/workflow-employee-space')
    expect(workbench?.component).not.toBe(workspace?.component)
    expect(graph?.path).toBe('/workflow-employee-space/stitch-full')
  })
})
