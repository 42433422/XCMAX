import { describe, expect, it } from 'vitest'

import { modMenu, modRoutes } from '../../../XCAGI/mods/attendance-industry/frontend/routes.js'

describe('attendance-industry management routes', () => {
  it('exposes the original business-management areas before conversion/settings', () => {
    expect(modMenu.map((item) => item.label)).toEqual(['人员管理', '部门管理', '排班资源', '考勤记录', '考勤表转换', '考勤设置'])
    expect(modMenu.some((item) => item.label === '考勤看板')).toBe(false)
  })

  it('registers a route for every management menu entry', () => {
    const paths = new Set(modRoutes.map((route) => route.path))
    for (const item of modMenu) expect(paths.has(item.path)).toBe(true)
  })
})
