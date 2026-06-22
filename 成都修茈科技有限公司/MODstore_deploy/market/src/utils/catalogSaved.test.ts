import { describe, it, expect, beforeEach } from 'vitest'
import { isCatalogSaved, toggleCatalogSaved } from './catalogSaved'

describe('isCatalogSaved', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns false when catalog is not saved', () => {
    expect(isCatalogSaved('catalog-1')).toBe(false)
  })

  it('returns true when catalog is saved', () => {
    localStorage.setItem('market_catalog_saved_v1', JSON.stringify(['catalog-1']))
    expect(isCatalogSaved('catalog-1')).toBe(true)
  })

  it('returns false for null id', () => {
    expect(isCatalogSaved(null)).toBe(false)
  })

  it('returns false for undefined id', () => {
    expect(isCatalogSaved(undefined)).toBe(false)
  })

  it('returns false for empty string id', () => {
    expect(isCatalogSaved('')).toBe(false)
  })

  it('handles numeric id by converting to string', () => {
    localStorage.setItem('market_catalog_saved_v1', JSON.stringify(['42']))
    expect(isCatalogSaved(42)).toBe(true)
  })

  it('returns false when localStorage is empty', () => {
    expect(isCatalogSaved('anything')).toBe(false)
  })

  it('returns false when localStorage contains invalid JSON', () => {
    localStorage.setItem('market_catalog_saved_v1', 'not json')
    expect(isCatalogSaved('x')).toBe(false)
  })

  it('returns false when localStorage contains non-array JSON', () => {
    localStorage.setItem('market_catalog_saved_v1', JSON.stringify({ not: 'array' }))
    expect(isCatalogSaved('x')).toBe(false)
  })

  it('coerces stored ids to strings', () => {
    localStorage.setItem('market_catalog_saved_v1', JSON.stringify([123, 456]))
    expect(isCatalogSaved('123')).toBe(true)
    expect(isCatalogSaved(456)).toBe(true)
  })
})

describe('toggleCatalogSaved', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('adds a new catalog and returns true', () => {
    const result = toggleCatalogSaved('catalog-1')
    expect(result).toBe(true)
    expect(isCatalogSaved('catalog-1')).toBe(true)
    const raw = localStorage.getItem('market_catalog_saved_v1')
    expect(JSON.parse(raw || '[]')).toEqual(['catalog-1'])
  })

  it('removes an existing catalog and returns false', () => {
    toggleCatalogSaved('catalog-1')
    const result = toggleCatalogSaved('catalog-1')
    expect(result).toBe(false)
    expect(isCatalogSaved('catalog-1')).toBe(false)
  })

  it('toggles twice returns to original state', () => {
    expect(toggleCatalogSaved('x')).toBe(true)
    expect(toggleCatalogSaved('x')).toBe(false)
    expect(toggleCatalogSaved('x')).toBe(true)
    expect(isCatalogSaved('x')).toBe(true)
  })

  it('handles numeric id', () => {
    expect(toggleCatalogSaved(42)).toBe(true)
    expect(isCatalogSaved(42)).toBe(true)
    expect(isCatalogSaved('42')).toBe(true)
    expect(toggleCatalogSaved(42)).toBe(false)
  })

  it('preserves other saved catalogs when toggling one', () => {
    toggleCatalogSaved('a')
    toggleCatalogSaved('b')
    toggleCatalogSaved('c')
    expect(isCatalogSaved('a')).toBe(true)
    expect(isCatalogSaved('b')).toBe(true)
    expect(isCatalogSaved('c')).toBe(true)
    toggleCatalogSaved('b')
    expect(isCatalogSaved('a')).toBe(true)
    expect(isCatalogSaved('b')).toBe(false)
    expect(isCatalogSaved('c')).toBe(true)
  })

  it('writes to localStorage with correct key', () => {
    toggleCatalogSaved('test')
    expect(localStorage.getItem('market_catalog_saved_v1')).not.toBeNull()
  })

  it('handles empty initial localStorage', () => {
    expect(toggleCatalogSaved('first')).toBe(true)
  })

  it('handles corrupted localStorage data by starting fresh', () => {
    localStorage.setItem('market_catalog_saved_v1', 'corrupted data')
    expect(toggleCatalogSaved('new')).toBe(true)
    expect(isCatalogSaved('new')).toBe(true)
  })
})
