import { describe, expect, it } from 'vitest'

import { modMenu, modRoutes } from '../../../XCAGI/mods/attendance-industry/frontend/routes.js'

describe('attendance-industry workspace routes', () => {
  it('exposes one attendance workspace instead of six top-level menus', () => {
    expect(modMenu.map((item) => item.label)).toEqual(['考勤工作区'])
    expect(modMenu.some((item) => item.label === '考勤看板')).toBe(false)
  })

  it('registers a route for every management menu entry', () => {
    const paths = new Set(modRoutes.map((route) => route.path))
    for (const item of modMenu) expect(paths.has(item.path)).toBe(true)
  })

  it('keeps all six business sections inside the same workspace component', () => {
    const root = modRoutes.find((route) => route.name === 'attendance-industry-workspace')
    for (const section of ['personnel', 'departments', 'schedules', 'records', 'convert', 'settings']) {
      const route = modRoutes.find((item) => item.path === `/attendance-industry/${section}`)
      expect(route?.component).toBe(root?.component)
      expect(route?.props).toEqual({ section })
    }
    expect(modRoutes.find((route) => route.name === 'attendance-industry-home')?.path).toBe('/attendance-industry/convert')
    expect(modRoutes.find((route) => route.path.endsWith('/dashboard'))?.redirect).toEqual({ name: 'attendance-industry-workspace' })
  })
})
