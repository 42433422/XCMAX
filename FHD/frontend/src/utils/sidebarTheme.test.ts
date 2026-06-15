import { describe, expect, it, beforeEach } from 'vitest'
import {
  applySidebarTheme,
  readStoredSidebarTheme,
  persistSidebarTheme,
  SIDEBAR_THEME_OPTIONS,
  SIDEBAR_THEME_STORAGE_KEY,
} from './sidebarTheme'

describe('sidebarTheme', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.removeAttribute('data-sidebar-theme')
  })

  it('exposes theme options', () => {
    expect(SIDEBAR_THEME_OPTIONS.length).toBeGreaterThan(2)
  })

  it('defaults to office-default', () => {
    expect(readStoredSidebarTheme()).toBe('office-default')
  })

  it('applies dark theme attribute', () => {
    persistSidebarTheme('dark-navy')
    expect(localStorage.getItem(SIDEBAR_THEME_STORAGE_KEY)).toBe('dark-navy')
    expect(document.body.getAttribute('data-sidebar-theme')).toBe('dark-navy')
  })

  it('removes attribute for office-default', () => {
    document.body.setAttribute('data-sidebar-theme', 'dark-navy')
    applySidebarTheme('office-default')
    expect(document.body.hasAttribute('data-sidebar-theme')).toBe(false)
  })

  it('migrates legacy light-* page theme', () => {
    localStorage.setItem('settingsPageTheme', 'light-blue')
    expect(readStoredSidebarTheme()).toBe('office-default')
  })
})
