/** Mod 列表项类型（与 stores/mods 解耦，避免 erpDomainPaths ↔ mods 循环依赖） */

export interface ModWorkflowEmployee {
  id: string
  label: string
  summary?: string
  panel_summary?: string
  panel_title?: string
  status_poll_path?: string
  agent_control_prefix?: string
  phone_agent_api_base?: string
  phone_agent_status_poll?: boolean
  workflow_placeholder?: boolean
}

export interface ModInfo {
  id: string
  name: string
  version: string
  author: string
  description: string
  type?: string
  primary?: boolean
  comms_exports?: string[]
  menu?: Array<{
    id: string
    label: string
    icon: string
    path: string
  }>
  frontend?: {
    pro_entry_path?: string
    [key: string]: unknown
  }
  menu_overrides?: Array<{
    key: string
    label?: string
    icon?: string
    hidden?: boolean
  }>
  industry?: {
    id?: string
    name?: string
    [key: string]: unknown
  }
  ui_labels?: Record<string, unknown>
  ui_starter_pack?: Array<Record<string, unknown>>
  workflow_employees?: ModWorkflowEmployee[]
  tutorial?: {
    tracks?: Array<{
      id: string
      title: string
      summary?: string
      description?: string
      requires_mod_menu?: boolean
      recommended?: boolean
    }>
    steps?: Array<Record<string, unknown>>
    page_highlights?: Record<string, Array<Record<string, unknown>>>
  }
}
