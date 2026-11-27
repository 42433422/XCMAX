import { canShowModelServiceBilling, MODEL_SERVICE_NAVIGATION } from '@/constants/modelServiceNavigation'

export interface DesktopNavigationItem {
  id: string
  label: string
  breadcrumb: string[]
  kind: 'page' | 'user_action'
}

type SettingsVisibility = 'signedIn' | 'localAdmin' | 'tenantRoles' | 'extensions' | 'modelPayment'
type SettingsNavigationNode = {
  id: string
  kind?: DesktopNavigationItem['kind']
  requires?: SettingsVisibility
  children?: readonly SettingsNavigationNode[]
} & ({ label: string } | { labelKey: string })

export const SETTINGS_ENTRIES = {
  profile: { id: 'profile-home', labelKey: 'settings.profileHome', requires: 'signedIn' },
  roles: { id: 'tenant-roles', label: '角色与权限', requires: 'tenantRoles' },
  audit: { id: 'audit-logs', labelKey: 'settings.securityAudit', requires: 'localAdmin' },
  intent: { id: 'intent', labelKey: 'settings.aiIntent' },
  memory: { id: 'memory-v2', labelKey: 'settings.persySystem' },
  mobile: { id: 'mobile-pairing', labelKey: 'settings.mobilePairing' },
  extensions: { id: 'extensions', labelKey: 'settings.extensions', requires: 'extensions' },
  versions: { id: 'distillation-versions', labelKey: 'settings.distillationVersions' },
  about: { id: 'about', labelKey: 'settings.about' },
} as const satisfies Record<string, SettingsNavigationNode>

export const BASIC_SETTINGS_ENTRY = {
  id: 'basic', labelKey: 'settings.basicSettings', children: [SETTINGS_ENTRIES.mobile, SETTINGS_ENTRIES.extensions],
}

export const SETTINGS_NAV_GROUPS = {
  account: {
    id: 'settings-group-account', label: '账号', icon: 'fa-user-o',
    children: [SETTINGS_ENTRIES.profile, SETTINGS_ENTRIES.roles],
  },
  intelligence: {
    id: 'settings-group-intelligence', label: '智能与数据', icon: 'fa-cubes',
    children: [MODEL_SERVICE_NAVIGATION, SETTINGS_ENTRIES.audit, SETTINGS_ENTRIES.intent, SETTINGS_ENTRIES.memory],
  },
  system: {
    id: 'settings-group-system', label: '系统与外观', icon: 'fa-sliders',
    children: [BASIC_SETTINGS_ENTRY],
  },
  about: {
    id: 'settings-group-about', label: '关于', icon: 'fa-info-circle',
    children: [SETTINGS_ENTRIES.versions, SETTINGS_ENTRIES.about],
  },
}

type SettingsAccount = {
  localUserId: number | null
  userRole: string
  accountKind: string
  tenantId: number | null
  marketIsEnterprise: boolean
  permissions: readonly string[]
}

export function isSettingsLocalAdmin(role?: string | null): boolean {
  return ['admin', 'superadmin'].includes(String(role || '').toLowerCase())
}

export function canManageTenantRoleSettings(account: Pick<SettingsAccount, 'accountKind' | 'tenantId' | 'marketIsEnterprise' | 'permissions'>): boolean {
  return account.accountKind === 'enterprise' && account.tenantId !== null &&
    account.marketIsEnterprise && account.permissions.includes('tenant.manage_roles')
}

export function readSettingsNavigation(
  rootLabel: string,
  account: SettingsAccount,
  mods: { mods: readonly { id?: string }[]; clientModsUiOff: boolean },
  adminConsole: boolean,
  translate: (key: string) => string,
): DesktopNavigationItem[] {
  const signedIn = account.localUserId != null
  const visible: Record<SettingsVisibility, boolean> = {
    signedIn,
    localAdmin: signedIn && isSettingsLocalAdmin(account.userRole),
    tenantRoles: canManageTenantRoleSettings(account),
    extensions: !mods.clientModsUiOff,
    modelPayment: canShowModelServiceBilling(mods.mods, adminConsole),
  }
  function toEntries(node: SettingsNavigationNode, breadcrumb: string[]): DesktopNavigationItem[] {
    if (node.requires && !visible[node.requires]) return []
    const label = 'label' in node ? node.label : translate(node.labelKey)
    return [
      { id: node.id, label, breadcrumb, kind: node.kind || 'page' },
      ...(node.children || []).flatMap(child => toEntries(child, [...breadcrumb, label])),
    ]
  }
  return Object.values(SETTINGS_NAV_GROUPS).flatMap(group => toEntries(group, [rootLabel]))
}
