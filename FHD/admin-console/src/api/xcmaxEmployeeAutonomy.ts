import api from '@/api/core'

/** MODstore employee-autonomy surface (proxied via FHD market admin when needed). */
const PREFIX = '/api/xcmax/market-proxy/admin/employee-autonomy'

async function empGet<T = Record<string, unknown>>(path: string, params?: Record<string, unknown>) {
  try {
    return await api.get<T>(`${PREFIX}${path}`, params)
  } catch (e: unknown) {
    const err = e as { status?: number }
    if (err?.status === 404) {
      return api.get<T>(`/api/admin/employee-autonomy${path}`, params)
    }
    throw e
  }
}

async function empPost<T = Record<string, unknown>>(path: string, body?: Record<string, unknown>) {
  try {
    return await api.post<T>(`${PREFIX}${path}`, body || {})
  } catch (e: unknown) {
    const err = e as { status?: number }
    if (err?.status === 404) {
      return api.post<T>(`/api/admin/employee-autonomy${path}`, body || {})
    }
    throw e
  }
}

async function runtimeGet<T = Record<string, unknown>>() {
  try {
    return await api.get<T>('/api/xcmax/market-proxy/scheduler/runtime')
  } catch (e: unknown) {
    const err = e as { status?: number }
    if (err?.status === 404) {
      return api.get<T>('/api/scheduler/runtime')
    }
    throw e
  }
}

export const xcmaxEmployeeAutonomyApi = {
  dashboard() {
    return empGet('/dashboard')
  },
  listSuggestions(params: Record<string, unknown> = {}) {
    return empGet('/suggestions', params)
  },
  approveSuggestion(id: string | number) {
    return empPost(`/suggestions/${encodeURIComponent(String(id))}/approve`)
  },
  rejectSuggestion(id: string | number, reason?: string) {
    return empPost(`/suggestions/${encodeURIComponent(String(id))}/reject`, { reason })
  },
  batchReview(payload: {
    ids: Array<string | number>
    action: 'approve' | 'reject'
    reason?: string
    dispatch_now?: boolean
  }) {
    return empPost('/suggestions/batch-review', payload)
  },
  listQuestions(params: Record<string, unknown> = {}) {
    return empGet('/questions', params)
  },
  answerQuestion(
    id: string | number,
    answer: string,
    answers?: Record<string, string>,
  ) {
    const body: Record<string, unknown> = {}
    if (answer) body.answer = answer
    if (answers && Object.keys(answers).length) body.answers = answers
    return empPost(`/questions/${encodeURIComponent(String(id))}/answer`, body)
  },
  scorecard(params: Record<string, unknown> = {}) {
    return empGet('/scorecard', params)
  },
  executionCoverage(params: Record<string, unknown> = {}) {
    return empGet('/execution-coverage', params)
  },
  runtime() {
    return runtimeGet()
  },
  employeeScorecard(employeeId: string, params: Record<string, unknown> = {}) {
    return empGet(`/scorecard/${encodeURIComponent(employeeId)}`, params)
  },
}
