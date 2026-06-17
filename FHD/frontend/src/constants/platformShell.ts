/** 通用化宿主壳（阶段 4）— 与 GET /api/platform-shell/capabilities 对齐 */

export const BRIDGE_MOD_IDS = [
  'xcagi-approval-bridge',
  'xcagi-lan-license-bridge',
  'xcagi-model-payment-bridge',
  'xcagi-planner-bridge',
] as const

export type BridgeModId = (typeof BRIDGE_MOD_IDS)[number]

export const PLATFORM_SHELL_POLICY =
  '新业务应做成 Mod（房子）或 employee_pack（家具），勿再写入宿主 workflow-employees.json'

export interface PlatformShellCapabilities {
  schema_version?: number
  edition?: 'minimal' | 'generic' | 'full'
  core_workflow_mod_id?: string
  protected_client_mod_ids?: string[]
  minimal_pack_installed?: boolean
  generic_pack_installed?: boolean
  platform_shell_mode?: boolean
  shell_api_prefixes?: string[]
  bridge_mods?: Array<{
    mod_id: string
    role: string
    host_api_prefixes: string[]
    installed: boolean
  }>
  policy?: string
}

export interface DeliverableStatus {
  schema_version?: number
  deliverable?: boolean
  edition?: 'minimal' | 'generic' | 'full'
  edition_ready?: boolean
  minimal_pack_installed?: boolean
  generic_pack_installed?: boolean
  missing_mod_ids?: string[]
  host_foundation_employee_installed?: boolean
  host_foundation_bridges_ready?: boolean
  host_foundation_materialize?: Record<string, unknown> | null
  blockers?: Array<{ code: string; message: string; missing_mod_ids?: string[] }>
  next_actions?: string[]
}

export interface IndustryBaselineItem {
  mod_id: string
  label: string
  tier: 'core' | 'host' | 'optional' | 'custom' | 'industry_package' | 'account_custom'
  required: boolean
  installed: boolean
  show_mod_id?: boolean
  delivery_seed_package?: AccountDeliverySeedPackage
}

export interface IndustryBaselineGroup {
  id: string
  title: string
  hint: string
  items: IndustryBaselineItem[]
}

export interface IndustryPackageRef {
  mod_id: string
  product_name: string
}

export interface AccountDeliverySeedPackage {
  mod_id?: string
  pkg_id: string
  version?: string
  artifact?: string
  apply?: string
  description?: string
}

export interface OnboardingIndustryPackage {
  industry_id: string
  name?: string
  scenario?: string
  product_name: string
  mod_id: string
  selectable?: boolean
}

export interface OnboardingIndustryCatalog {
  schema_version?: number
  open_industry_ids: string[]
  open_packages: OnboardingIndustryPackage[]
  preview_packages?: OnboardingIndustryPackage[]
  /** 企业 entitlement 已裁剪开放列表 */
  enterprise_filter_applied?: boolean
  owner_id?: string | null
  selected_industry_id?: string | null
}

export interface IndustryBaselinePlan {
  schema_version?: number
  industry_id: string
  summary?: string
  industry_package?: IndustryPackageRef | null
  groups: IndustryBaselineGroup[]
  required_mod_ids: string[]
  optional_mod_ids: string[]
  industry_mod_ids: string[]
  custom_mod_ids?: string[]
  missing_required_mod_ids: string[]
  missing_optional_mod_ids: string[]
  missing_industry_mod_ids: string[]
  account_custom_mod_ids?: string[]
  missing_account_custom_mod_ids?: string[]
  account_delivery_seed_packages?: AccountDeliverySeedPackage[]
  custom_employee_extension_mod_ids?: string[]
  host_baseline_ready?: boolean
  account_custom_ready?: boolean
  baseline_ready: boolean
  full_stack_ready?: boolean
  industry_mod_ready: boolean
}

export interface EmployeePlannerStatus {
  installed_employee_pack_count: number
  registered_tool_count: number
  registered_tool_names: string[]
  office_catalog_count: number
  office_installed_count: number
  office_installed_ids: string[]
  missing_office_pack_ids: string[]
  office_ready: boolean
  runtime_missing_pack_ids: string[]
  routes_reloaded?: string[]
}
