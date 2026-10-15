import { YUANGON_PKG_ROLE_LABELS } from '@/domain/yuangonDutyRoster'

export type EmployeeSsotContactRecord = {
  employee_id: string
  display_name: string
  surface_name?: string
  department?: string
  source?: string
  installed?: boolean
  runnable?: boolean
  online?: boolean
  pinned?: boolean
  avatar_key?: string
  contact_route?: string
  mobile_contact_route?: string
  capabilities?: string[]
  last_task_status?: string
  description?: string
}

export type EmployeeSsotContact = {
  id: string
  display_name: string
  username: string
  subtitle: string
  description: string
  area: string
  status: string
  api_base_path: string
  phone_channel: string
  is_duty_employee_entry: true
  source?: string
  installed?: boolean
  runnable?: boolean
  pinned?: boolean
}

export type EmployeeSsotPayload = {
  contacts?: EmployeeSsotContactRecord[]
  employee_labels?: Record<string, string>
  employee_descriptions?: Record<string, string>
  admin?: {
    departments?: Array<{
      id?: string
      key?: string
      label?: string
      employees?: Array<{ id?: string; on_duty?: boolean | null }>
    }>
    on_duty_employee_ids?: string[] | null
  }
  enterprise?: {
    layers?: Array<{ id?: string; label?: string }>
    employees?: Record<
      string,
      {
        id?: string
        label?: string
        listing?: string
        enterprise_layer?: string
        description?: string
      }
    >
  }
}

/** 客户可读员工名：后端真实名优先；后端回显英文 ID 时用 SSOT label / 编制表中文名兜底。 */
function nameForEmployee(
  id: string,
  row: EmployeeSsotContactRecord | null,
  payload: EmployeeSsotPayload | null | undefined,
): string {
  const backendName = String(row?.display_name || '').trim()
  if (backendName && backendName !== id) return backendName
  return String(payload?.employee_labels?.[id] || YUANGON_PKG_ROLE_LABELS[id] || backendName || id).trim() || id
}

function descriptionForEmployee(id: string, payload: EmployeeSsotPayload | null | undefined, fallback = ''): string {
  const descriptions = payload?.employee_descriptions || {}
  return String(descriptions[id] || fallback).trim()
}

/** 部门/层级英文 ID → 客户可读的中文部门名（管理端六线 label 或企业端四层 label）。 */
function areaLabelFor(
  id: string,
  row: EmployeeSsotContactRecord,
  payload: EmployeeSsotPayload | null | undefined,
): string {
  const raw = String(row.department || '').trim()
  const admin = payload?.admin?.departments || []
  for (const dept of admin) {
    if (raw && (dept.id === raw || dept.key === raw)) {
      return String(dept.label || dept.id || '').trim() || '编制'
    }
  }
  const layers = payload?.enterprise?.layers || []
  const layerLabel = (layerId: string): string => {
    for (const layer of layers) {
      if (layer.id === layerId) return String(layer.label || layer.id || '').trim() || '编制'
    }
    return ''
  }
  if (raw) {
    const byDept = layerLabel(raw)
    if (byDept) return byDept
  }
  const entLayer = String(payload?.enterprise?.employees?.[id]?.enterprise_layer || '').trim()
  if (entLayer) return layerLabel(entLayer) || '编制'
  return '编制'
}

function mapContactRecord(row: EmployeeSsotContactRecord, payload: EmployeeSsotPayload | null | undefined): EmployeeSsotContact | null {
  const id = String(row.employee_id || '').trim()
  if (!id) return null
  const displayName = nameForEmployee(id, row, payload)
  const areaLabel = areaLabelFor(id, row, payload)
  const installed = Boolean(row.installed)
  const runnable = Boolean(row.runnable ?? installed)
  const source = String(row.source || (installed ? 'installed' : 'planned')).trim()
  const contactRoute = String(row.contact_route || row.mobile_contact_route || `/api/admin/employees/${id}`).trim()
  return {
    id,
    display_name: displayName,
    username: id,
    subtitle: runnable ? `${areaLabel} · 可执行` : `${areaLabel} · 未安装`,
    description:
      String(row.description || '').trim() ||
      descriptionForEmployee(id, payload, runnable ? '已安装，可联系' : '编制内但未安装员工包'),
    area: areaLabel,
    status: runnable ? 'on_duty' : 'planned',
    api_base_path: contactRoute.replace(/\/chat\/?$/, '').replace(/\/messages\/?$/, '') || `/api/admin/employees/${id}`,
    phone_channel: source.startsWith('codex') || source === 'builtin' ? 'super' : 'admin-duty',
    is_duty_employee_entry: true,
    source,
    installed,
    runnable,
    pinned: Boolean(row.pinned),
  }
}

/** 将 platform-shell / mobile employee-ssot 派生包转为 IM 侧栏联系人。 */
export function dutyEmployeesFromEmployeeSsot(payload: EmployeeSsotPayload | null | undefined): EmployeeSsotContact[] {
  const contacts = payload?.contacts
  if (Array.isArray(contacts) && contacts.length) {
    const out: EmployeeSsotContact[] = []
    const seen = new Set<string>()
    for (const row of contacts) {
      if (!row || typeof row !== 'object') continue
      const source = String(row.source || '').trim()
      if (source === 'builtin' || source === 'codex') continue
      const mapped = mapContactRecord(row, payload)
      if (!mapped || seen.has(mapped.id)) continue
      seen.add(mapped.id)
      out.push(mapped)
    }
    return out.sort((a, b) => {
      if (Boolean(a.runnable) !== Boolean(b.runnable)) {
        return a.runnable ? -1 : 1
      }
      return a.display_name.localeCompare(b.display_name, 'zh-CN')
    })
  }

  if (!payload?.admin?.departments?.length) return []
  const out: EmployeeSsotContact[] = []
  const onDutySet = new Set(payload.admin.on_duty_employee_ids || [])
  for (const dept of payload.admin.departments) {
    const area = String(dept.label || dept.id || '').trim() || '编制'
    for (const emp of dept.employees || []) {
      const id = String(emp.id || '').trim()
      if (!id) continue
      const onDuty = emp.on_duty ?? onDutySet.has(id)
      out.push({
        id,
        display_name: nameForEmployee(id, null, payload),
        username: id,
        subtitle: onDuty ? `${area} · 可执行` : `${area} · 未安装`,
        description: descriptionForEmployee(id, payload, onDuty ? '已安装，可联系' : '编制内但未安装员工包'),
        area,
        status: onDuty ? 'on_duty' : 'planned',
        api_base_path: `/api/admin/employees/${id}`,
        phone_channel: 'admin-duty',
        is_duty_employee_entry: true,
        source: onDuty ? 'installed' : 'planned',
        installed: onDuty,
        runnable: onDuty,
      })
    }
  }
  return out
}
