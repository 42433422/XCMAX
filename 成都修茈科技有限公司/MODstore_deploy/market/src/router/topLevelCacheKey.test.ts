import { describe, expect, it } from 'vitest'
import { resolveTopLevelRouterCacheKey } from './topLevelCacheKey'

describe('resolveTopLevelRouterCacheKey', () => {
  it('returns the WorkbenchView bucket for the landing route (redirects to /workbench/home)', () => {
    expect(
      resolveTopLevelRouterCacheKey({ path: '/', name: 'home', fullPath: '/' }),
    ).toBe('cache-workbench-view')
  })

  it('returns the WorkbenchView bucket for /workbench/* child routes', () => {
    expect(
      resolveTopLevelRouterCacheKey({
        path: '/workbench/home',
        name: 'workbench-home',
        fullPath: '/workbench/home',
      }),
    ).toBe('cache-workbench-view')

    expect(
      resolveTopLevelRouterCacheKey({
        path: '/workbench/unified',
        name: 'workbench-unified',
        fullPath: '/workbench/unified?focus=repository',
      }),
    ).toBe('cache-workbench-view')

    expect(
      resolveTopLevelRouterCacheKey({
        path: '/workbench/mod/abc',
        name: 'mod-authoring',
        fullPath: '/workbench/mod/abc',
      }),
    ).toBe('cache-workbench-view')
  })

  // 关键回归：/workbench/shell/* 必须落到 WorkbenchShell 自己的桶里，
  // 不能与 /workbench/home 共桶，否则 keep-alive 会取错 vnode 并触发
  // `parentComponent.ctx.deactivate is not a function`。
  it('returns the WorkbenchShell bucket for /workbench/shell/* (not the WorkbenchView bucket)', () => {
    const shellKey = resolveTopLevelRouterCacheKey({
      path: '/workbench/shell/employee/123',
      name: 'workbench-shell',
      fullPath: '/workbench/shell/employee/123',
    })
    const homeKey = resolveTopLevelRouterCacheKey({
      path: '/workbench/home',
      name: 'workbench-home',
      fullPath: '/workbench/home',
    })

    expect(shellKey).toBe('cache-workbench-shell-v2')
    expect(shellKey).not.toBe(homeKey)
    expect(shellKey).not.toBe('cache-workbench-view')
  })

  it('routes WorkbenchShell by name even if the URL path overlaps /workbench/', () => {
    expect(
      resolveTopLevelRouterCacheKey({
        path: '/workbench/shell/workflow/wf-1',
        name: 'workbench-shell',
        fullPath: '/workbench/shell/workflow/wf-1?fromAi=1',
      }),
    ).toBe('cache-workbench-shell-v2')
  })

  it('falls back to fullPath for unrelated routes', () => {
    expect(
      resolveTopLevelRouterCacheKey({
        path: '/plans',
        name: 'plans',
        fullPath: '/plans',
      }),
    ).toBe('/plans')

    expect(
      resolveTopLevelRouterCacheKey({
        path: '/script-workflows/123',
        name: 'script-workflow-detail',
        fullPath: '/script-workflows/123?tab=runs',
      }),
    ).toBe('/script-workflows/123?tab=runs')
  })

  it('handles symbol route names without throwing', () => {
    const sym = Symbol('not-found')
    expect(
      resolveTopLevelRouterCacheKey({ path: '/random', name: sym, fullPath: '/random' }),
    ).toBe('/random')
  })

  it('handles missing path/name/fullPath gracefully', () => {
    expect(
      resolveTopLevelRouterCacheKey({ path: undefined, name: undefined, fullPath: undefined }),
    ).toBe('/')
  })
})
