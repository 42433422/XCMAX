import type { LeField, LeFieldId, LeGrid } from './leTypes'

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}

/** Preserve field IDs, binding/style metadata and exact geometry; never invent sample fields. */
export function normalizeLabelFields(value: unknown): LeField[] {
  if (!Array.isArray(value)) throw new Error('模板没有有效字段数据，请重新识别标签或联系管理员。')
  const usedIds = new Set<LeFieldId>()
  return value.map((raw, index) => {
    const field = asRecord(raw)
    const position = asRecord(field.position)
    const label = String(field.label ?? field.name ?? `字段${index + 1}`)
    const normalizedPosition = { ...position } as LeField['position']
    for (const key of ['left', 'top', 'width', 'height'] as const) {
      const rawValue = position[key]
      const number = Number(rawValue)
      if (rawValue == null || rawValue === '' || !Number.isFinite(number)
        || ((key === 'width' || key === 'height') && number <= 0)) {
        throw new Error(`字段「${label}」缺少有效位置或尺寸，无法安全编辑。请重新识别标签。`)
      }
      normalizedPosition[key] = number
    }
    const id: LeFieldId = typeof field.id === 'string' || typeof field.id === 'number'
      ? field.id : `editor-field-${index + 1}`
    if (usedIds.has(id)) throw new Error('模板字段标识重复，无法安全编辑。')
    usedIds.add(id)
    return {
      ...field, id, label, value: String(field.value ?? ''),
      type: String(field.type || 'dynamic'), position: normalizedPosition,
    }
  })
}

export function normalizeLabelGrid(value: unknown): LeGrid | null {
  if (value == null) return null
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('模板网格数据无效，请返回模板列表重新识别标签。')
  }
  const grid = asRecord(value) as LeGrid
  for (const key of ['horizontal_lines', 'vertical_lines'] as const) {
    if (grid[key] != null && (!Array.isArray(grid[key]) || !grid[key]!.every(Number.isFinite))) {
      throw new Error('模板网格数据无效，请重新识别标签。')
    }
  }
  return grid
}

export function labelCanvasSize(preview: Record<string, unknown>) {
  const size = asRecord(preview.image_size)
  const width = Number(size.width ?? 900)
  const height = Number(size.height ?? 600)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error('模板画布尺寸无效，请重新识别标签。')
  }
  return { width, height }
}
