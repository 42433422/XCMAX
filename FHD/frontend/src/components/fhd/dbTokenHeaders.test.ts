import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  readStoredDbTokens,
  saveStoredDbTokens,
  saveStoredReadToken,
  dbReadHeaders,
  dbWriteHeaders,
  urlNeedsDbReadToken,
  urlNeedsDbWriteToken,
  combinedRequestUrl,
  LS_DB_READ_TOKEN,
  LS_DB_WRITE_TOKEN,
  FHD_DB_READ_UNLOCKED_EVENT,
} from '@/components/fhd/dbTokenHeaders'

describe('dbTokenHeaders', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('exports correct constants', () => {
    expect(LS_DB_READ_TOKEN).toBe('xcagi_db_read_token')
    expect(LS_DB_WRITE_TOKEN).toBe('xcagi_db_write_token')
    expect(FHD_DB_READ_UNLOCKED_EVENT).toBe('fhd-db-read-unlocked')
  })

  it('readStoredDbTokens returns empty strings when nothing stored', () => {
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('')
    expect(tokens.write).toBe('')
  })

  it('readStoredDbTokens returns stored tokens', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'read-token')
    localStorage.setItem(LS_DB_WRITE_TOKEN, 'write-token')
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('read-token')
    expect(tokens.write).toBe('write-token')
  })

  it('readStoredDbTokens trims whitespace', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, '  read-token  ')
    localStorage.setItem(LS_DB_WRITE_TOKEN, '  write-token  ')
    const tokens = readStoredDbTokens()
    expect(tokens.read).toBe('read-token')
    expect(tokens.write).toBe('write-token')
  })

  it('saveStoredDbTokens saves tokens to localStorage', () => {
    saveStoredDbTokens('my-read', 'my-write')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('my-read')
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBe('my-write')
  })

  it('saveStoredDbTokens removes empty tokens from localStorage', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'old')
    localStorage.setItem(LS_DB_WRITE_TOKEN, 'old')
    saveStoredDbTokens('', '')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBeNull()
  })

  it('saveStoredDbTokens trims before saving', () => {
    saveStoredDbTokens('  trimmed  ', '  trimmed  ')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('trimmed')
    expect(localStorage.getItem(LS_DB_WRITE_TOKEN)).toBe('trimmed')
  })

  it('saveStoredReadToken saves read token only', () => {
    saveStoredReadToken('my-read-token')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBe('my-read-token')
  })

  it('saveStoredReadToken removes token when empty', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'old')
    saveStoredReadToken('')
    expect(localStorage.getItem(LS_DB_READ_TOKEN)).toBeNull()
  })

  it('dbReadHeaders returns header when read token exists', () => {
    localStorage.setItem(LS_DB_READ_TOKEN, 'test-read')
    expect(dbReadHeaders()).toEqual({ 'X-FHD-Db-Read-Token': 'test-read' })
  })

  it('dbReadHeaders returns empty object when no read token', () => {
    expect(dbReadHeaders()).toEqual({})
  })

  it('dbWriteHeaders returns header when write token exists', () => {
    localStorage.setItem(LS_DB_WRITE_TOKEN, 'test-write')
    expect(dbWriteHeaders()).toEqual({ 'X-FHD-Db-Write-Token': 'test-write' })
  })

  it('dbWriteHeaders returns empty object when no write token', () => {
    expect(dbWriteHeaders()).toEqual({})
  })

  it('urlNeedsDbReadToken matches /api/products/ paths', () => {
    expect(urlNeedsDbReadToken('/api/products/list')).toBe(true)
    expect(urlNeedsDbReadToken('/api/products/1')).toBe(true)
    expect(urlNeedsDbReadToken('/api/orders/list')).toBe(false)
    expect(urlNeedsDbReadToken('/api/other')).toBe(false)
  })

  it('urlNeedsDbReadToken handles full URLs', () => {
    expect(urlNeedsDbReadToken('https://example.com/api/products/list')).toBe(true)
  })

  it('urlNeedsDbWriteToken matches write paths with non-GET methods', () => {
    expect(urlNeedsDbWriteToken('/api/products/update', 'POST')).toBe(true)
    expect(urlNeedsDbWriteToken('/api/products/add', 'POST')).toBe(true)
    expect(urlNeedsDbWriteToken('/api/products/delete', 'DELETE')).toBe(true)
    expect(urlNeedsDbWriteToken('/api/products/batch-delete', 'POST')).toBe(true)
  })

  it('urlNeedsDbWriteToken returns false for GET methods', () => {
    expect(urlNeedsDbWriteToken('/api/products/update', 'GET')).toBe(false)
    expect(urlNeedsDbWriteToken('/api/products/add', 'HEAD')).toBe(false)
    expect(urlNeedsDbWriteToken('/api/products/delete', 'OPTIONS')).toBe(false)
  })

  it('urlNeedsDbWriteToken returns false for non-matching paths', () => {
    expect(urlNeedsDbWriteToken('/api/products/list', 'POST')).toBe(false)
    expect(urlNeedsDbWriteToken('/api/orders/update', 'POST')).toBe(false)
  })

  it('combinedRequestUrl combines base and path', () => {
    expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: '/test' }))
      .toBe('https://api.example.com/test')
  })

  it('combinedRequestUrl returns full URL when url is absolute', () => {
    expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: 'https://other.com/api' }))
      .toBe('https://other.com/api')
  })

  it('combinedRequestUrl handles relative paths', () => {
    expect(combinedRequestUrl({ baseURL: 'https://api.example.com', url: 'test' }))
      .toBe('https://api.example.com/test')
  })

  it('combinedRequestUrl handles missing baseURL', () => {
    expect(combinedRequestUrl({ url: '/api/test' })).toBe('/api/test')
  })

  it('combinedRequestUrl handles missing url', () => {
    expect(combinedRequestUrl({ baseURL: 'https://api.example.com' }))
      .toBe('https://api.example.com/')
  })
})
