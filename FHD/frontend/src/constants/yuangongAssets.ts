/**
 * 员工空间 yuangong 分层素材（`frontend/public/yuangong`）。
 * 源图可放在 `XCAGI/yuangong`，构建/同步后复制为 desk.png / staff.png。
 *
 * 路径须带 `import.meta.env.BASE_URL`：管理端 Vite `base=/admin/`，裸 `/yuangong/...` 会 404。
 */
function publicAsset(path: string): string {
  const raw = String(path || '').trim()
  if (!raw || /^https?:\/\//i.test(raw)) return raw
  const base = String(import.meta.env.BASE_URL || '/')
  const root = base.endsWith('/') ? base : `${base}/`
  const rel = raw.startsWith('/') ? raw.slice(1) : raw
  return `${root}${rel}`
}

export const YUANGONG_BASE = publicAsset('/yuangong')

/** PNG 由 XCAGI/yuangong 同步后可选；仓库默认可用 SVG */
export const YUANGONG_DESK_PNG = `${YUANGONG_BASE}/desk.png`
export const YUANGONG_DESK_SVG = `${YUANGONG_BASE}/desk.svg`
export const YUANGONG_STAFF_PNG = `${YUANGONG_BASE}/staff.png`
export const YUANGONG_STAFF_SVG = `${YUANGONG_BASE}/staff.svg`
export const YUANGONG_STAFF_BUSY_PNG = `${YUANGONG_BASE}/staff-busy.png`
export const YUANGONG_STAFF_BUSY_SVG = `${YUANGONG_BASE}/staff-busy.svg`

export const YUANGONG_FALLBACK_DESK = publicAsset('/workflow/desk.svg')
export const YUANGONG_FALLBACK_STAFF = publicAsset('/workflow/worker-idle.svg')
export const YUANGONG_FALLBACK_STAFF_BUSY = publicAsset('/workflow/worker-busy.svg')

/** 员工空间入口横幅：员工拼接全景图（与下方工位实况呼应） */
export const YUANGONG_ENTRY_STITCH_PNG = `${YUANGONG_BASE}/stitch-tutorial.png`

/** 员工工位像素全景（热点见 `yuangongEmployeeHotspots.ts`） */
export const YUANGONG_EMPLOYEE_SCENE_PNG = `${YUANGONG_BASE}/员工.png`

/** 入口横幅回退（与横幅、全图页共用） */
export const YUANGONG_ENTRY_WORKFLOW_PNG = publicAsset('/workflow/employee-space-bg.png')
export const YUANGONG_ENTRY_WORKFLOW_SVG = publicAsset('/workflow/employee-space-bg.svg')
