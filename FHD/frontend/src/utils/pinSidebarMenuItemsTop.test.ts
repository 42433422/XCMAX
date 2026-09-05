import { afterEach, describe, expect, it, vi } from 'vitest'
import { ADMIN_SIDEBAR_PINNED_TOP_KEYS } from '../../../admin-console/src/constants/adminOperatorNav'

vi.mock('@/constants/adminOperatorNav', async () => await import('../../../admin-console/src/constants/adminOperatorNav'))

import { pinSidebarMenuItemsTop } from './pinSidebarMenuItemsTop'

afterEach(() => vi.unstubAllEnvs())

describe('pinSidebarMenuItemsTop', () => {
  it('moves chat to the front without dropping other items', () => {
    const items = [
      { key: 'products', name: '人员' },
      { key: 'other-tools', name: '工作流' },
      { key: 'chat', name: '智能对话' },
      { key: 'orders', name: '考勤单' },
    ]
    expect(pinSidebarMenuItemsTop(items).map((i) => i.key)).toEqual(['chat', 'products', 'other-tools', 'orders'])
  })

  it.each(['mod-planner-chat', 'mod-mod-planner-chat'])('pins the canonical planner key %s', (key) => {
    const items = [{ key: 'orders' }, { key: 'products' }, { key }, { key: 'customers' }]
    expect(pinSidebarMenuItemsTop(items)).toEqual([items[2], items[0], items[1], items[3]])
    expect(items.map((item) => item.key)).toEqual(['orders', 'products', key, 'customers'])
  })

  it('does not infer chat from unrelated Mod names or path suffixes', () => {
    const items = [
      { key: 'orders' },
      { key: 'mod-other-chat', name: '智能对话', path: '/mod/other/chat' },
      { key: 'mod-planner-chat-debug', path: '/mod/xcagi-planner-bridge/chat-debug' },
      { key: 'products' },
    ]
    expect(pinSidebarMenuItemsTop(items)).toEqual(items)
  })

  it('preserves both host and planner entries if a transition temporarily contains both', () => {
    const items = [{ key: 'orders' }, { key: 'mod-planner-chat' }, { key: 'products' }, { key: 'chat' }]
    expect(pinSidebarMenuItemsTop(items)).toEqual([items[1], items[3], items[0], items[2]])
  })

  it('preserves the actual admin console pinned order and all remaining entries', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    const rest = [{ key: 'unrelated' }, { key: 'mod-other-chat' }]
    const items = [...rest, ...[...ADMIN_SIDEBAR_PINNED_TOP_KEYS].reverse().map((key) => ({ key }))]
    expect(pinSidebarMenuItemsTop(items).map((item) => item.key)).toEqual([...ADMIN_SIDEBAR_PINNED_TOP_KEYS, ...rest.map((item) => item.key)])
  })
})
