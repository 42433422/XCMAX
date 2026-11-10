/** Capsule templates and worksheet templates share one optional selection rule. */

export function initialOptionalTemplateIndex(optional: boolean): number {
  return optional ? -1 : 0
}

/** Opening the picker does not select. Busy, non-integer, or out-of-range picks are ignored. */
export function pickOptionalTemplate(length: number, index: number, busy = false): number | null {
  if (busy || typeof index !== 'number' || !Number.isInteger(index) || index < 0 || index >= length) return null
  return index
}

export function isOfficeEltToolMessage(message: string): boolean {
  const text = String(message || '')
  return /(?:\.xlsx|\.xlsm|\.xls|\.csv|\.docx|\.doc|\.pdf|\.pptx|\.ppt)/i.test(text)
    && /导入|入库|解析办公/.test(text)
}
