import api, { ApiError, primeCsrfCookie } from './core'
import type { RequestOptions } from './core'
import { readCsrfTokenFromCookie } from '@/utils/csrfCookie'
import { captureAuthSession } from '@/utils/authSessionCache'

// A rejected CSRF request never reaches the handler. Concurrent initial GETs can
// replace the cookie after a POST reads it, so retry only that explicit rejection.
async function reviewedExcelPost(path: string, form: FormData) {
  const sessionCurrent = captureAuthSession()
  const requireCurrentSession = () => {
    if (!sessionCurrent()) throw Object.assign(new Error('登录身份已变化，已停止后续原件处理；已发出的请求请在原账号核对'), { name: 'ReviewedExcelSessionChangedError' })
  }
  try {
    requireCurrentSession()
    if (path.endsWith('/preview') || path.endsWith('/classify') || path.endsWith('/archive-classify') || path.endsWith('/archive-quota') || path.includes('/archive-assets/') || path.includes('/archive-versions/')) {
      const identity = await api.get<{ actor: string }>('/api/templates/reviewed-excel/identity')
      requireCurrentSession()
      if (!identity.actor) throw new Error('无法确认当前登录身份')
      form.set('expected_actor', identity.actor)
    }
    if (!readCsrfTokenFromCookie()) await primeCsrfCookie()
    requireCurrentSession()
    for (let attempt = 0; ; attempt++) {
      requireCurrentSession()
      try {
        const result = await api.post(path, form)
        requireCurrentSession()
        return result
      } catch (error) {
        requireCurrentSession()
        if (!(error instanceof ApiError) || error.status !== 403 ||
            !['CSRF token missing', 'CSRF token mismatch'].includes(error.message) || attempt >= 2) throw error
        if (!readCsrfTokenFromCookie()) await primeCsrfCookie()
        requireCurrentSession()
        await new Promise((resolve) => setTimeout(resolve, 50))
      }
    }
  } catch (error) {
    requireCurrentSession()
    throw error
  }
}
/**
 * 开发环境下若把 VITE_TEMPLATE_* 配成 http://127.0.0.1:5000/api/... 绝对地址，
 * 用户从局域网 IP 打开前端时，api 封装会跨域直连 5000，预检 Origin（192.168.*）不在白名单则整页 API 全挂。
 * 故在 DEV 且 host 为 localhost/127.0.0.1 时强制改为相对路径，走 Vite 同源代理。
 */
function getConfiguredEndpoint(envKey: string, fallbackPath: string): string {
  const configured = String(import.meta.env[envKey] || '').trim()
  if (!configured) return fallbackPath
  if (import.meta.env.DEV && /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i.test(configured)) {
    try {
      const u = new URL(configured)
      const path = `${u.pathname}${u.search}`
      return path || fallbackPath
    } catch {
      return configured
    }
  }
  return configured
}

const TEMPLATE_ENDPOINTS = {
  list: getConfiguredEndpoint('VITE_TEMPLATE_LIST_ENDPOINT', '/api/templates'),
  detail: getConfiguredEndpoint('VITE_TEMPLATE_DETAIL_ENDPOINT', '/api/templates'),
  analyze: getConfiguredEndpoint('VITE_TEMPLATE_ANALYZE_ENDPOINT', '/api/templates/analyze'),
  upload: getConfiguredEndpoint('VITE_TEMPLATE_UPLOAD_ENDPOINT', '/api/templates/upload'),
  progress: getConfiguredEndpoint('VITE_TEMPLATE_PROGRESS_ENDPOINT', '/api/templates/progress'),
  create: getConfiguredEndpoint('VITE_TEMPLATE_CREATE_ENDPOINT', '/api/templates/create'),
  update: getConfiguredEndpoint('VITE_TEMPLATE_UPDATE_ENDPOINT', '/api/templates/update'),
  remove: getConfiguredEndpoint('VITE_TEMPLATE_DELETE_ENDPOINT', '/api/templates/delete'),
  extractGrid: getConfiguredEndpoint('VITE_TEMPLATE_EXTRACT_GRID_ENDPOINT', '/api/templates/extract-grid'),
  excelDecompose: getConfiguredEndpoint('VITE_TEMPLATE_DECOMPOSE_ENDPOINT', '/api/excel/template/decompose'),
}

function joinPath(base: string, segment: string | number): string {
  const normalizedBase = String(base || '').replace(/\/+$/, '')
  const normalizedSegment = String(segment || '').replace(/^\/+/, '')
  return `${normalizedBase}/${normalizedSegment}`
}

function wrapServiceAvailabilityError(error: unknown, actionName: string, endpoint: string): never {
  const unavailableStatus = new Set([404, 405, 501])
  if (error instanceof ApiError && unavailableStatus.has(error.status)) {
    throw new ApiError(`模板${actionName}服务未开放，请检查接口配置：${endpoint}`, error.status, error.data)
  }
  throw error
}

export const templatePreviewApi = {
  endpoints: TEMPLATE_ENDPOINTS,

  classifyExcel(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/classify', formData)
  },

  archiveClassifyExcel(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/archive-classify', formData)
  },

  archiveQuota() { return api.get('/api/templates/reviewed-excel/archive-quota') },
  setArchiveQuota(formData: FormData) { return reviewedExcelPost('/api/templates/reviewed-excel/archive-quota', formData) },
  archiveAssets() { return api.get('/api/templates/reviewed-excel/archive-assets') },
  appendArchiveVersion(id: string, formData: FormData) { return reviewedExcelPost(`/api/templates/reviewed-excel/archive-assets/${encodeURIComponent(id)}/versions`, formData) },
  downloadArchiveVersion(id: string) { return api.download(`/api/templates/reviewed-excel/archive-versions/${encodeURIComponent(id)}/download`) },
  setArchiveAssetState(id: string, formData: FormData) { return reviewedExcelPost(`/api/templates/reviewed-excel/archive-assets/${encodeURIComponent(id)}/state`, formData) },
  recoverArchiveVersion(id: string, formData: FormData) { return reviewedExcelPost(`/api/templates/reviewed-excel/archive-versions/${encodeURIComponent(id)}/recover`, formData) },
  classifyArchiveVersion(id: string, formData: FormData) { return reviewedExcelPost(`/api/templates/reviewed-excel/archive-versions/${encodeURIComponent(id)}/classify`, formData) },

  analyzeClassification(id: string, formData: FormData) {
    return reviewedExcelPost(`/api/templates/reviewed-excel/classifications/${encodeURIComponent(id)}/analyze`, formData)
  },

  autoSlices(id: string, version: string) {
    return api.get(`/api/templates/reviewed-excel/classifications/${encodeURIComponent(id)}/auto-slices/${encodeURIComponent(version)}`)
  },

  downloadAutoSlice(id: string, version: string, index: number) {
    return api.download(`/api/templates/reviewed-excel/classifications/${encodeURIComponent(id)}/auto-slices/${encodeURIComponent(version)}/${index}`)
  },

  confirmClassification(id: string, formData: FormData) {
    return reviewedExcelPost(`/api/templates/reviewed-excel/classifications/${encodeURIComponent(id)}/confirm`, formData)
  },

  recentClassifications() {
    return api.get('/api/templates/reviewed-excel/classifications')
  },

  downloadClassificationSource(id: string) {
    return api.download(`/api/templates/reviewed-excel/classifications/${encodeURIComponent(id)}/source`)
  },

  reviewExcel(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/preview', formData)
  },

  refineReviewedExcel(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/refine', formData)
  },

  reviewedExcelHistory(id: string) {
    return api.get(`/api/templates/reviewed-excel/reviews/${encodeURIComponent(id)}`)
  },

  downloadReviewedCandidate(id: string, version: string, candidate: string) {
    return api.download(`/api/templates/reviewed-excel/reviews/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(candidate)}/download`)
  },

  previewReviewedIntake(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/intake-preview', formData)
  },

  saveReviewedExcel(formData: FormData) {
    return reviewedExcelPost('/api/templates/reviewed-excel/save', formData)
  },

  downloadReviewedExcel(id: string) {
    const numeric = String(id).replace(/^db:/, '')
    if (!/^\d+$/.test(numeric)) throw new Error('模板编号无效')
    return api.download(`/api/templates/reviewed-excel/${numeric}/download`)
  },

  listTemplates(options?: RequestOptions) {
    return api.get(TEMPLATE_ENDPOINTS.list, {}, options || {})
  },

  getTemplateDetail(templateId: string | number) {
    return api.get(joinPath(TEMPLATE_ENDPOINTS.detail, templateId))
  },

  decomposeTemplate(payload: Record<string, unknown>) {
    return api.post(TEMPLATE_ENDPOINTS.excelDecompose, payload)
  },

  analyzeTemplate(formData: FormData) {
    return api.post(TEMPLATE_ENDPOINTS.analyze, formData)
  },

  /** 解析办公文件并自动入库模版库（analyze → create）。 */
  uploadTemplate(formData: FormData) {
    return api.post(TEMPLATE_ENDPOINTS.upload, formData)
  },

  getAnalysisProgress(taskId: string | number) {
    return api.get(joinPath(TEMPLATE_ENDPOINTS.progress, taskId))
  },

  async createTemplate(payload: Record<string, unknown>) {
    try {
      return await api.post(TEMPLATE_ENDPOINTS.create, payload)
    } catch (error) {
      wrapServiceAvailabilityError(error, '创建', TEMPLATE_ENDPOINTS.create)
    }
  },

  async updateTemplate(payload: Record<string, unknown>) {
    try {
      return await api.post(TEMPLATE_ENDPOINTS.update, payload)
    } catch (error) {
      wrapServiceAvailabilityError(error, '更新', TEMPLATE_ENDPOINTS.update)
    }
  },

  async createTemplateFromGrid(payload: Record<string, unknown>) {
    try {
      return await api.post(TEMPLATE_ENDPOINTS.create, payload)
    } catch (error) {
      wrapServiceAvailabilityError(error, '创建', TEMPLATE_ENDPOINTS.create)
    }
  },

  async replaceTemplateById(payload: Record<string, unknown>) {
    try {
      return await api.post(TEMPLATE_ENDPOINTS.update, payload)
    } catch (error) {
      wrapServiceAvailabilityError(error, '替换', TEMPLATE_ENDPOINTS.update)
    }
  },

  deleteTemplate(payload: Record<string, unknown>) {
    return api.post(TEMPLATE_ENDPOINTS.remove, payload)
  },

  extractGrid(formData: FormData) {
    return api.post(TEMPLATE_ENDPOINTS.extractGrid, formData)
  },
}

export default templatePreviewApi
