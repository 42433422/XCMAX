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

function labelForEmployee(id: string, payload: EmployeeSsotPayload | null | undefined): string {
  const labels = payload?.employee_labels || {}
  return String(labels[id] || id).trim() || id
}

function descriptionForEmployee(id: string, payload: EmployeeSsotPayload | null | undefined, fallback = ''): string {
  const descriptions = payload?.employee_descriptions || {}
  return String(descriptions[id] || fallback).trim()
}

function mapContactRecord(row: EmployeeSsotContactRecord, payload: EmployeeSsotPayload | null | undefined): EmployeeSsotContact | null {
  const id = String(row.employee_id || '').trim()
  if (!id) return null
  const displayName = String(row.display_name || labelForEmployee(id, payload) || id).trim()
  const department = String(row.department || '编制').trim() || '编制'
  const installed = Boolean(row.installed)
  const runnable = Boolean(row.runnable ?? installed)
  const source = String(row.source || (installed ? 'installed' : 'planned')).trim()
  const contactRoute = String(row.contact_route || row.mobile_contact_route || `/api/admin/employees/${id}`).trim()
  return {
    id,
    display_name: displayName,
    username: id,
    subtitle: runnable ? `${department} · 可执行` : source === 'planned' ? `${department} · 未安装` : `${department} · ${source}`,
    description:
      String(row.description || '').trim() ||
      descriptionForEmployee(id, payload, runnable ? '已安装，可联系' : '编制内但未安装 employee_pack'),
    area: department,
    status: runnable ? 'on_duty' : source === 'planned' ? 'planned' : source,
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
        display_name: labelForEmployee(id, payload),
        username: id,
        subtitle: onDuty ? `${area} · 可执行` : `${area} · 未安装`,
        description: descriptionForEmployee(id, payload, onDuty ? '已安装，可联系' : '编制内但未安装 employee_pack'),
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
