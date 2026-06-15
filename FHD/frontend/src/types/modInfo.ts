/** Mod 列表项类型（与 stores/mods 解耦，避免 erpDomainPaths ↔ mods 循环依赖） */

export interface ModWorkflowEmployee {
  id: string
  label: string
  /** 任务面板摘要；与 panel_summary 二选一，优先 summary */
  summary?: string
  /** 任务面板摘要（manifest 常用字段名） */
  panel_summary?: string
  /** 覆盖默认标题「工作流 · {label}」 */
  panel_title?: string
  /** 若设置，聊天任务面板将定期 GET 该绝对路径，响应 data 合并进工作流状态 */
  status_poll_path?: string
  /** 若设置，开关打开/关闭时分别 POST {prefix}/start、{prefix}/stop */
  agent_control_prefix?: string
  /** 与 phone_agent_status_poll 联用：POST/GET 的 API 根（如 /api/mod/xxx/phone-agent） */
  phone_agent_api_base?: string
  /** 为 true 时轮询 GET {phone_agent_api_base}/status */
  phone_agent_status_poll?: boolean
  /** 占位员工：仅展示摘要与简单步骤，无状态轮询 */
  workflow_placeholder?: boolean
}

/** 运行时 Mod manifest（/api/mods/ 下发） */
export interface ModInfo {
  id: string
  name: string
  version: string
  author: string
  description: string
  /** 后端 list_mods：mod | employee_pack 等 */
  type?: string
  /** 与后端 manifest primary 一致，主扩展优先用于顶栏角标等 */
  primary?: boolean
  /** 后端 manifest artifact 字段 */
  artifact?: string
  /** manifest comms.exports，声明本 Mod 提供的通信通道（文档用，实际以注册为准） */
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
  primary_workflow?: {
    title?: string
    steps?: Array<string | Record<string, unknown>>
  }
  workflow_employees?: ModWorkflowEmployee[]
  /** 可选：贡献教程路线、步骤或页内高亮 */
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
