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
}

export type EmployeeSsotPayload = {
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

/** 将 platform-shell employee-ssot 派生包转为 IM 侧栏联系人（管理端编制优先）。 */
export function dutyEmployeesFromEmployeeSsot(
  payload: EmployeeSsotPayload | null | undefined,
): EmployeeSsotContact[] {
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
        display_name: id,
        username: id,
        subtitle: onDuty ? `${area} · 可执行` : `${area} · 未安装`,
        description: onDuty ? '已安装，可联系' : '编制内但未安装 employee_pack',
        area,
        status: onDuty ? 'on_duty' : 'planned',
        api_base_path: `/api/admin/employees/${id}`,
        phone_channel: 'admin-duty',
        is_duty_employee_entry: true,
      })
    }
  }
  return out
}
