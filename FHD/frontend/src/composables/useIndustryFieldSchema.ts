import { computed } from 'vue'
import { useIndustryStore } from '@/stores/industry'
import { asRecord, asArray, asString } from '@/utils/typeGuards'

export interface IndustryFieldDescriptor {
  key: string
  label: string
  type: string
  required: boolean
  unit: string
  semantic: string
  visible: boolean
  validators: Array<Record<string, unknown>>
}

export interface IndustryFieldValidationError {
  field: string
  label: string
  message: string
}

// 校验类型注册表（与后端 app/domain/services/industry_rules.py 的 VALIDATOR_REGISTRY 同形，数据驱动）
const FIELD_VALIDATORS: Record<string, (value: unknown, params: unknown) => string | null> = {
  oneOf(value, params) {
    if (value === null || value === undefined || value === '') return null
    const allowed = Array.isArray(params) ? params.map((x) => String(x)) : []
    if (!allowed.length) return null
    return allowed.includes(String(value)) ? null : `必须是 ${allowed.join('、')} 之一`
  },
  range(value, params) {
    if (value === null || value === undefined || value === '') return null
    const num = Number(value)
    if (Number.isNaN(num)) return null
    const p = (params && typeof params === 'object' ? params : {}) as Record<string, unknown>
    if (p.min !== undefined && num < Number(p.min)) return `不能小于 ${p.min}`
    if (p.max !== undefined && num > Number(p.max)) return `不能大于 ${p.max}`
    return null
  },
  regex(value, params) {
    if (value === null || value === undefined || value === '') return null
    const pattern =
      typeof params === 'string' ? params : String((params as Record<string, unknown>)?.pattern || '')
    if (!pattern) return null
    try {
      return new RegExp(pattern).test(String(value)) ? null : '格式不正确'
    } catch {
      return null
    }
  },
  not_expired(value) {
    if (value === null || value === undefined || value === '') return null
    const d = new Date(String(value))
    if (Number.isNaN(d.getTime())) return null
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    return d < today ? '已过保质期（到期日早于今天）' : null
  },
}

/**
 * 行业感知子系统 schema：菜单键(子系统身份) → 当前行业下该子系统的
 * ``{ label, visible, entity, fields[] }``。
 *
 * 数据来自后端行业 profile 的 ``config.subsystems[menuKey]``
 * （IndustryContextMiddleware 从 User.industry_id 注入当前行业 → /api/system/industry 下发），
 * 由各行业 Mod 的 ``manifest.industry.subsystems`` 声明。无声明时回退空数组，
 * 调用方据此沿用各自的默认字段/标签（向后兼容）。
 *
 * 与 useIndustryUiText 并列：后者产出单字符串文案，本 composable 产出结构化字段集。
 */
export function useIndustryFieldSchema(menuKey: string) {
  const industryStore = useIndustryStore()

  // currentConfig 有两种形状，均需兼容：
  //  - server 路径：{ id, name, code, description, config: { units, ..., subsystems } }
  //  - mod 兜底路径：{ id, name, code, description, config, ...modIndustry }（subsystems 在顶层）
  const subsystem = computed<Record<string, unknown>>(() => {
    const root = asRecord(industryStore.currentConfig)
    const inner = asRecord(root.config)
    const subsystems = asRecord(
      (inner.subsystems as unknown) ?? (root.subsystems as unknown),
    )
    return asRecord(subsystems[menuKey])
  })

  const fields = computed<IndustryFieldDescriptor[]>(() =>
    asArray<Record<string, unknown>>(subsystem.value.fields)
      .map((raw) => {
        const rec = asRecord(raw)
        const key = asString(rec.key, '')
        if (!key) return null
        return {
          key,
          label: asString(rec.label, key),
          type: asString(rec.type, 'text'),
          required: rec.required === true,
          unit: asString(rec.unit, ''),
          semantic: asString(rec.semantic, ''),
          visible: rec.visible !== false,
          validators: asArray<Record<string, unknown>>(rec.validators),
        } as IndustryFieldDescriptor
      })
      .filter((x): x is IndustryFieldDescriptor => x !== null),
  )

  /** 字段 key → 显示名（仅含 schema 声明的业务字段） */
  const labels = computed<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const f of fields.value) out[f.key] = f.label
    return out
  })

  /** 该子系统是否对当前行业暴露（缺省 true） */
  const visible = computed<boolean>(() => subsystem.value.visible !== false)

  /** 业务实体名（如 产品/人员、客户/部门） */
  const entity = computed<string>(() => asString(subsystem.value.entity, ''))

  /** 子系统行业标签（如 产品管理/人员管理） */
  const label = computed<string>(() => asString(subsystem.value.label, ''))

  /** 当前行业是否声明了该子系统的字段 schema */
  const hasSchema = computed<boolean>(() => fields.value.length > 0)

  /** 取某字段显示名；无 schema 声明时回退到 fallback（或 key 本身） */
  function labelOf(key: string, fallback?: string): string {
    return labels.value[key] || fallback || key
  }

  /** 按当前行业该子系统的字段 validators 校验一条记录（与后端 industry_rules 同形、数据驱动） */
  function validate(record: Record<string, unknown>): IndustryFieldValidationError[] {
    const out: IndustryFieldValidationError[] = []
    const rec = record || {}
    for (const f of fields.value) {
      const value = rec[f.key]
      if (f.required && (value === null || value === undefined || String(value).trim() === '')) {
        out.push({ field: f.key, label: f.label, message: `${f.label}不能为空` })
        continue
      }
      for (const v of f.validators) {
        const vtype = String(asRecord(v).type || '')
        const handler = FIELD_VALIDATORS[vtype]
        if (!handler) continue
        const msg = handler(value, asRecord(v).params)
        if (msg) out.push({ field: f.key, label: f.label, message: `${f.label}${msg}` })
      }
    }
    return out
  }

  return { subsystem, fields, labels, labelOf, visible, entity, label, hasSchema, validate }
}

export default useIndustryFieldSchema
