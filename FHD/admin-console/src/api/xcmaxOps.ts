import api from '@/api/core'

export const xcmaxOpsApi = {
  dutyHealth() {
    return api.get('/api/xcmax/ops/duty-health')
  },
  dispatch(body: Record<string, unknown>) {
    return api.post('/api/xcmax/ops/dispatch', body)
  },
  listJobs(limit = 20) {
    return api.get('/api/xcmax/ops/jobs', { limit })
  },
  closureStatus() {
    return api.get('/api/xcmax/ops/closure-status')
  },
  staffingOnboard(body: Record<string, unknown>) {
    return api.post('/api/xcmax/ops/staffing/onboard', body)
  },
  staffingInstallLocal(body: Record<string, unknown>) {
    return api.post('/api/xcmax/ops/staffing/install-local', body)
  },
  staffingCloseGap(body: Record<string, unknown>) {
    return api.post('/api/xcmax/ops/staffing/close-gap', body)
  },
  createDutyRun(body: Record<string, unknown>) {
    return api.post('/api/xcmax/ops/duty-runs', body)
  },
  dutyRunDetail(runId: number) {
    return api.get(`/api/xcmax/ops/duty-runs/${runId}`)
  },
}
