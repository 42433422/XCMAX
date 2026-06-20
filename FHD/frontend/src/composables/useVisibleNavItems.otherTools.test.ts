import { describe, expect, it } from 'vitest'
import { mergeSidebarMenuItems } from '@/utils/mergeSidebarMenuItems'
import { MOD_MENU_ID_TO_HOST_NAV_KEY } from '@/constants/genericModPack'

function hostNavKeyHasContributingModFacet(
  hostNavKey: string,
  modMenuItems: Array<{ key: string; path?: string }>,
): boolean {
  const key = String(hostNavKey || '').trim()
  if (!key) return false
  for (const item of modMenuItems) {
    const navKey = String(item.key || '')
      .trim()
      .replace(/^mod-mod-/, 'mod-')
    if (MOD_MENU_ID_TO_HOST_NAV_KEY[navKey] === key) return true
    const path = String(item.path || '').trim()
    const tail = path.split('/').filter(Boolean).pop() || ''
    if (tail === key) return true
  }
  return false
}

describe('员工工作流侧栏可见性', () => {
  it('Mod 贡献 mod-office-other-tools 时映射到员工空间槽位', () => {
    expect(
      hostNavKeyHasContributingModFacet('workflow-employee-space', [
        {
          key: 'mod-office-other-tools',
          path: '/mod/xcagi-office-employee-pack-bridge/other-tools',
        },
      ]),
    ).toBe(true)
  })

  it('合并侧栏时 admin 运维项与 core 项在同一 core 批次', () => {
    const merged = mergeSidebarMenuItems(
      [
        { key: 'xcmax-admin', name: '服务器后台总览', iconClass: 'fa-dashboard' },
        { key: 'workflow-employee-space', name: '员工空间', iconClass: 'fa-th-large' },
        { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
      ],
      [],
      [{ key: 'admin-entitlements', name: '用户管理', iconClass: 'fa-shield' }],
      [],
      ['xcagi-office-employee-pack-bridge'],
      '',
    )
    expect(merged.map((m) => m.key)).toEqual([
      'xcmax-admin',
      'workflow-employee-space',
      'chat',
      'admin-entitlements',
    ])
  })
})
