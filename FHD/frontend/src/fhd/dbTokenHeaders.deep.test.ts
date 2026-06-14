import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  isProductsReadGateGraceActive,
  touchProductsReadGateGrace,
  readStoredDbTokens,
  saveStoredDbTokens,
  urlNeedsDbReadToken,
  shouldAttachDbReadToken,
  urlNeedsDbWriteToken,
  dbReadHeaders,
  dbWriteHeaders,
  armNextPlannerChatDbWriteToken,
  isPlannerChatDbWriteTokenArmed,
  consumePlannerChatDbWriteTokenArm,
  LS_DB_READ_TOKEN,
} from './dbTokenHeaders'

describe('dbTokenHeaders deep', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('exports storage keys', () => {
    expect(LS_DB_READ_TOKEN).toContain('read_token')
  })

  it('touchProductsReadGateGrace activates grace window', () => {
    expect(isProductsReadGateGraceActive()).toBe(false)
    touchProductsReadGateGrace()
    expect(isProductsReadGateGraceActive()).toBe(true)
  })

  it('save and read stored db tokens', () => {
    saveStoredDbTokens('read-tok', 'write-tok')
    expect(readStoredDbTokens()).toEqual({ read: 'read-tok', write: 'write-tok' })
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('read-tok')
  })

  it('urlNeedsDbReadToken detects product api paths', () => {
    expect(urlNeedsDbReadToken('/api/products/list')).toBe(true)
    expect(urlNeedsDbReadToken('/api/health')).toBe(false)
  })

  it('shouldAttachDbReadToken respects GET method', () => {
    expect(shouldAttachDbReadToken('/api/products/list', 'GET')).toBe(true)
    expect(shouldAttachDbReadToken('/api/products/list', 'POST')).toBe(false)
  })

  it('urlNeedsDbWriteToken detects write paths', () => {
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(true)
  })

  it('dbReadHeaders returns empty without token', () => {
    expect(dbReadHeaders()).toEqual({})
  })

  it('dbReadHeaders includes token when stored', () => {
    saveStoredDbTokens('r1', '')
    const headers = dbReadHeaders({ ignoreGrace: true })
    expect(headers['X-FHD-Db-Read-Token']).toBe('r1')
  })

  it('planner chat write token arm lifecycle', () => {
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
    armNextPlannerChatDbWriteToken()
    expect(isPlannerChatDbWriteTokenArmed()).toBe(true)
    consumePlannerChatDbWriteTokenArm()
    expect(isPlannerChatDbWriteTokenArmed()).toBe(false)
  })

  it('dbWriteHeaders includes write token', () => {
    saveStoredDbTokens('', 'w1')
    expect(dbWriteHeaders()['X-FHD-Db-Write-Token']).toBe('w1')
  })
})
