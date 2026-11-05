import { beforeEach, describe, expect, it } from 'vitest'
import { clearRouteChunkError, isChunkLoadError, isUnmatchedRoute, markRouteChunkError, routeChunkErrorPath } from './routeLoadState'
import { ADMIN_HOST_ROUTE_RECORDS } from '../../../admin-console/src/adminHostRoutes'

describe('routeLoadState', () => {
  beforeEach(() => clearRouteChunkError())
  it('recognises lazy chunk load failures only', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: /admin/assets/js/X.js'))).toBe(true)
    expect(isChunkLoadError({ name: 'ChunkLoadError', message: '' })).toBe(true)
    expect(isChunkLoadError(new Error('Unable to preload CSS for /admin/assets/x.css'))).toBe(true)
    expect(isChunkLoadError('Importing a module script failed.')).toBe(true)
    expect(isChunkLoadError(new Error('403 forbidden'))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
  })
  it('marks and clears the failed path', () => {
    markRouteChunkError('/delivery-center')
    expect(routeChunkErrorPath.value).toBe('/delivery-center')
    markRouteChunkError(undefined)
    expect(routeChunkErrorPath.value).toBe('/')
    clearRouteChunkError()
    expect(routeChunkErrorPath.value).toBe('')
  })
  it('treats only real unmatched paths as not found', () => {
    expect(isUnmatchedRoute({ matched: [], fullPath: '/users-x' })).toBe(true)
    expect(isUnmatchedRoute({ matched: [], fullPath: '/' })).toBe(false)
    expect(isUnmatchedRoute({ matched: [{}], fullPath: '/xcmax-admin' })).toBe(false)
    expect(isUnmatchedRoute({ matched: [], path: '' })).toBe(false)
    expect(isUnmatchedRoute({ matched: [], fullPath: '/x', name: 'named' })).toBe(false)
    expect(isUnmatchedRoute(null)).toBe(false)
  })
  it('redirects the hand-typed /users address to user management without new guards', () => {
    const record = ADMIN_HOST_ROUTE_RECORDS.find((row) => row.path === '/users')!
    expect(record.redirect).toEqual({ name: 'admin-entitlements' })
    expect(record.meta).toBeUndefined()
  })
})
