/** 标签字段位置 */
export interface LeFieldPosition {
  left: number
  top: number
  width: number
  height: number
  [key: string]: unknown
}

export type LeFieldId = string | number

/** 标签字段（编辑器内统一契约；type 实际取 'fixed' | 'dynamic'，识别结果可能给其他字符串，故放宽为 string） */
export interface LeField {
  id: LeFieldId
  label: string
  value: string
  type: string
  position: LeFieldPosition
  [key: string]: unknown
}

/** 标签网格（识别结果宽松契约） */
export interface LeGrid {
  horizontal_lines?: number[]
  vertical_lines?: number[]
  [key: string]: unknown
}
