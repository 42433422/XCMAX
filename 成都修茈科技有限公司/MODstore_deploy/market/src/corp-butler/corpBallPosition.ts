import { isCorpMobileViewport } from './corpViewport'

/** 官网悬浮球尺寸（与 .butler-ball 胶囊宽约 120px） */
export const CORP_BALL_W = 120
export const CORP_BALL_H = 56
export const CORP_BALL_STORAGE = 'xc_butler_pos_corp'

export function isContactPagePath(): boolean {
  if (typeof window === 'undefined') return false
  return /\/contact(?:\.html)?\/?$/i.test(window.location.pathname)
}

export function getCorpDefaultBallPosition(): { x: number; y: number } {
  const margin = 16
  const bottom = 24
  const y = Math.max(8, window.innerHeight - CORP_BALL_H - bottom)
  const mobile = isCorpMobileViewport()
  const x =
    isContactPagePath() || mobile
      ? margin
      : Math.max(8, window.innerWidth - CORP_BALL_W - margin)
  return { x, y }
}

/** 移动端右下角留给「回到顶部」，避免与 AI 管家叠在一起 */
function overlapsMobileBackToTop(x: number, y: number): boolean {
  if (!isCorpMobileViewport()) return false
  const zoneLeft = window.innerWidth - 72
  const zoneTop = window.innerHeight - 80
  return x >= zoneLeft && y >= zoneTop
}

export function clampCorpBallPosition(x: number, y: number): { x: number; y: number } {
  return {
    x: Math.max(8, Math.min(window.innerWidth - CORP_BALL_W - 8, x)),
    y: Math.max(8, Math.min(window.innerHeight - CORP_BALL_H - 8, y)),
  }
}

export function loadCorpBallPosition(): { x: number; y: number } {
  try {
    const raw = localStorage.getItem(CORP_BALL_STORAGE)
    if (raw) {
      const p = JSON.parse(raw) as { x?: number; y?: number }
      if (typeof p.x === 'number' && typeof p.y === 'number') {
        const clamped = clampCorpBallPosition(p.x, p.y)
        if (overlapsMobileBackToTop(clamped.x, clamped.y)) {
          return getCorpDefaultBallPosition()
        }
        return clamped
      }
    }
  } catch {
    // ignore
  }
  return getCorpDefaultBallPosition()
}

export function saveCorpBallPosition(x: number, y: number): { x: number; y: number } {
  const p = clampCorpBallPosition(x, y)
  try {
    localStorage.setItem(CORP_BALL_STORAGE, JSON.stringify(p))
  } catch {
    // ignore
  }
  return p
}
