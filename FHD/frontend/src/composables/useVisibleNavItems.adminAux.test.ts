import { describe, expect, it } from 'vitest'
import { ADMIN_OPERATOR_AUX_MENU_ITEMS } from '../../../admin-console/src/constants/adminOperatorNav'
import { mergeSidebarMenuItems } from '@/utils/mergeSidebarMenuItems'

describe('admin operator aux sidebar', () => {
  it('includes internal-customer-service in admin aux catalog', () => {
    const keys = ADMIN_OPERATOR_AUX_MENU_ITEMS.map((m) => m.key)
    expect(keys).toContain('internal-customer-service')
  })

  it('keeps im as the admin information entry', () => {
    const item = ADMIN_OPERATOR_AUX_MENU_ITEMS.find((m) => m.key === 'im')
    expect(item?.name).toBe('信息')
  })

  it('does not flatten employee-workflow children into admin aux trailing', () => {
    const keys = ADMIN_OPERATOR_AUX_MENU_ITEMS.map((m) => m.key)
    expect(keys).not.toContain('other-tools')
    expect(keys).not.toContain('workflow-employee-space')
    expect(keys).not.toContain('workflow-visualization')
  })

  it('merges admin aux trailing without duplicate mod slot', () => {
    const merged = mergeSidebarMenuItems(
      [
        { key: 'xcmax-admin', name: '服务器后台总览', iconClass: 'fa-dashboard' },
        { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
      ],
      [
        {
          key: 'mod-internal-customer-service',
          name: '内部客服',
          iconClass: 'fa-headphones',
          modId: 'xcagi-customer-service-bridge',
          path: '/mod/xcagi-customer-service-bridge/internal-customer-service',
        },
      ],
      [],
      ADMIN_OPERATOR_AUX_MENU_ITEMS.map((item) => ({ ...item })),
      ['xcagi-customer-service-bridge'],
      '',
    )
    expect(merged.map((m) => m.key)).toContain('internal-customer-service')
    expect(merged.map((m) => m.key)).not.toContain('mod-internal-customer-service')
  })
})
