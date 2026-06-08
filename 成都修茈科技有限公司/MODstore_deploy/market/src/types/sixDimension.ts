/** 与 modstore_server/employee_six_dimension 六维报告结构对齐 */

export type SixDimEntry = {
  score?: number
  grade?: string
  grade_label?: string
  label?: string
  description?: string
  reasons?: string[]
}

export type SixDimensionReport = {
  dimensions?: Record<string, SixDimEntry>
  overall_score?: number
  overall_grade?: string
  overall_grade_label?: string
  dimension_grades?: Record<string, string>
  passed?: boolean
  critical_failed?: boolean
  failed_dimensions?: string[]
  pipeline_label?: string
  grade_scale?: Record<string, string>
  pass_thresholds?: Record<string, number>
  scoring_source?: 'deterministic' | 'llm' | string
  llm_summary?: string
  recommend_release?: boolean
}

export type CatalogQualityGate = {
  passed?: boolean
  critical_failed?: boolean
  failed_dimensions?: string[]
  overall_score?: number
  overall_grade?: string
}

export type CatalogQualityResponse = {
  ok?: boolean
  validate_errors?: string[]
  validate_warnings?: string[]
  six_dimension?: SixDimensionReport | null
  gate?: CatalogQualityGate
  pipeline_label?: string
  audited_at?: string
  from_cache?: boolean
  six_dimension_llm_meta?: Record<string, unknown> | null
}
