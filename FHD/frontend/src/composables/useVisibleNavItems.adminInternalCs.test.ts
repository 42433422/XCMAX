import { describe, expect, it } from 'vitest'
import { mergeSidebarMenuItems } from '@/utils/mergeSidebarMenuItems'

describe('admin internal customer service sidebar', () => {
  it('filters mod-internal-customer-service from adminItems through merge', () => {
    const merged = mergeSidebarMenuItems(
      [{ key: 'chat', name: '智能对话', iconClass: 'fa-comments' }],
      [],
      [
        { key: 'admin-entitlements', name: '用户 Mod 管理', iconClass: 'fa-shield' },
        {
          key: 'mod-internal-customer-service',
          name: '内部客服',
          iconClass: 'fa-headphones',
          modId: 'xcagi-customer-service-bridge',
          path: '/mod/xcagi-customer-service-bridge/internal-customer-service',
        },
      ],
      [],
      ['xcagi-planner-bridge', 'xcagi-customer-service-bridge'],
      '',
    )
    expect(merged.map((m) => m.key)).not.toContain('mod-internal-customer-service')
    expect(merged.map((m) => m.key)).toContain('admin-entitlements')
  })
})
