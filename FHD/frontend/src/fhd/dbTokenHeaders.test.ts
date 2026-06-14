import { describe, expect, it, beforeEach } from 'vitest'
import {
  isProductsReadGateGraceActive,
  touchProductsReadGateGrace,
  LS_DB_READ_TOKEN,
  LS_DB_WRITE_TOKEN,
  FHD_STORED_DB_TOKENS_CHANGED_EVENT,
} from './dbTokenHeaders'

describe('dbTokenHeaders', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('exports storage keys and event names', () => {
    expect(LS_DB_READ_TOKEN).toBe('xcagi_db_read_token')
    expect(LS_DB_WRITE_TOKEN).toBe('xcagi_db_write_token')
    expect(FHD_STORED_DB_TOKENS_CHANGED_EVENT).toContain('db-tokens')
  })

  it('grace inactive by default', () => {
    expect(isProductsReadGateGraceActive()).toBe(false)
  })

  it('activates grace after touch', () => {
    touchProductsReadGateGrace()
    expect(isProductsReadGateGraceActive()).toBe(true)
  })
})
