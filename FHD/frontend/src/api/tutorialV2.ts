import api from './core'

export interface TutorialEvidenceDTO {
  step_id: string
  status: 'pending' | 'failed' | 'passed'
  result_code: string
  entity_refs: Array<{ type: string; id: string | number }>
  counts: Record<string, string | number>
  attempt_count: number
  verified_at: string | null
}

export interface TutorialStepDTO {
  id: string
  title: string
  goal: string
  instruction: string
  success_criteria: string
  why: string
  hint: string
  route_name: string
  target_selector: string
  required: boolean
  status: 'pending' | 'failed' | 'passed'
  evidence: TutorialEvidenceDTO | null
}

export interface TutorialRunDTO {
  id: string
  workspace_id: string
  course_id: string
  version: number
  status: 'active' | 'paused' | 'completed' | 'reset'
  current_step_id: string
  attempt_count: number
  progress: number
  completed_steps: number
  total_steps: number
  generation: number
  teaching_space: true
  steps: TutorialStepDTO[]
  started_at: string | null
  completed_at: string | null
}

export interface TutorialCourseDTO {
  id: string
  title: string
  summary: string
  estimated_minutes: number
  prerequisite_ids: string[]
  version: number
  steps: TutorialStepDTO[]
  locked: boolean
  missing_prerequisite_ids: string[]
  run: TutorialRunDTO | null
  status: 'not_started' | TutorialRunDTO['status']
  progress: number
}

type ApiEnvelope<T> = { success: boolean; data: T }

export const tutorialV2Api = {
  async courses(): Promise<TutorialCourseDTO[]> {
    const response = await api.get<ApiEnvelope<TutorialCourseDTO[]>>('/api/tutorial/v2/courses')
    return response.data
  },
  async start(courseId: string): Promise<TutorialRunDTO> {
    const response = await api.post<ApiEnvelope<TutorialRunDTO>>('/api/tutorial/v2/runs', {
      course_id: courseId,
    })
    return response.data
  },
  async current(): Promise<TutorialRunDTO | null> {
    const response = await api.get<ApiEnvelope<TutorialRunDTO | null>>('/api/tutorial/v2/runs/current')
    return response.data
  },
  async enter(runId: string): Promise<TutorialRunDTO> {
    const response = await api.post<ApiEnvelope<TutorialRunDTO>>(`/api/tutorial/v2/runs/${runId}/enter`)
    return response.data
  },
  async leave(runId: string): Promise<TutorialRunDTO> {
    const response = await api.post<ApiEnvelope<TutorialRunDTO>>(`/api/tutorial/v2/runs/${runId}/leave`)
    return response.data
  },
  async verify(runId: string, stepId: string, context: Record<string, unknown>) {
    const response = await api.post<ApiEnvelope<{
      run: TutorialRunDTO
      evidence: TutorialEvidenceDTO
      hint: string
    }>>(`/api/tutorial/v2/runs/${runId}/steps/${stepId}/verify`, { context })
    return response.data
  },
  async reset(runId: string): Promise<TutorialRunDTO> {
    const response = await api.post<ApiEnvelope<TutorialRunDTO>>(`/api/tutorial/v2/runs/${runId}/reset`)
    return response.data
  },
  async reports(): Promise<Array<Record<string, unknown>>> {
    const response = await api.get<ApiEnvelope<Array<Record<string, unknown>>>>('/api/tutorial/v2/reports')
    return response.data
  },
}

export default tutorialV2Api
