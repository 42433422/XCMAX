import { describe, expect, it } from 'vitest'
import { CORE_MENU_ITEMS_BASE, pinMenuKeyFirst, PRIMARY_CHAT_MENU_KEY, sidebarLayoutSeedKeys } from './coreMenuCatalog'

describe('coreMenuCatalog', () => {
  it('exposes business docking as a core menu item', () => {
    expect(CORE_MENU_ITEMS_BASE).toContainEqual(expect.objectContaining({ key: 'business-docking', name: '数据对接中心' }))
  })

  it('pinMenuKeyFirst moves chat to front', () => {
    const rows = [
      { key: 'mod-a', name: 'A' },
      { key: PRIMARY_CHAT_MENU_KEY, name: 'Chat' },
      { key: 'products', name: 'P' },
    ]
    expect(pinMenuKeyFirst(rows).map((r) => r.key)).toEqual([PRIMARY_CHAT_MENU_KEY, 'mod-a', 'products'])
  })

  it('sidebarLayoutSeedKeys starts with chat', () => {
    expect(sidebarLayoutSeedKeys()[0]).toBe(PRIMARY_CHAT_MENU_KEY)
  })
})
