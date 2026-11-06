import { describe, expect, it } from 'vitest'
import { SIDEBAR_CHAT_NAV_KEY, isChatLikePath, isChatSidebarActive, normalizeSidebarActiveKey } from './sidebarActiveKey'

describe('sidebarActiveKey', () => {
  it('isChatLikePath recognizes chat routes', () => {
    expect(isChatLikePath('/')).toBe(true)
    expect(isChatLikePath('/chat')).toBe(true)
    expect(isChatLikePath('/mods/foo/chat')).toBe(true)
    expect(isChatLikePath('/chat-debug')).toBe(false)
  })

  it('normalizeSidebarActiveKey maps planner chat to chat', () => {
    expect(normalizeSidebarActiveKey('mod-planner-chat')).toBe(SIDEBAR_CHAT_NAV_KEY)
    expect(normalizeSidebarActiveKey('other', { name: 'mod-planner-chat', path: '/x' })).toBe(SIDEBAR_CHAT_NAV_KEY)
    expect(normalizeSidebarActiveKey('inventory', { name: 'products', path: '/products' })).toBe('inventory')
  })

  it('normalizeSidebarActiveKey maps enterprise ERP mod routes back to the host sidebar key', () => {
    expect(normalizeSidebarActiveKey('mod-erp-customers', { name: 'mod-erp-customers', path: '/mod/xcagi-erp-domain-bridge/customers' })).toBe('customers')
    expect(normalizeSidebarActiveKey('mod-erp-products', { name: 'mod-erp-products', path: '/mod/xcagi-erp-domain-bridge/products' })).toBe('products')
    expect(normalizeSidebarActiveKey('mod-erp-orders', { name: 'mod-erp-orders', path: '/mod/xcagi-erp-domain-bridge/orders' })).toBe('orders')
  })

  it('isChatSidebarActive checks normalized key', () => {
    expect(isChatSidebarActive('mod-planner-chat', { name: 'mod-planner-chat', path: '/chat' })).toBe(true)
    expect(isChatSidebarActive('settings', { name: 'settings', path: '/settings' })).toBe(false)
  })
})
