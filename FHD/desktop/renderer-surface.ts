import type { BrowserWindow, Event as ElectronEvent, Input } from 'electron'

type WriteLog = (line: string) => void

/** A compositor that lost its GL buffer paints one near-white color (std ≈ 0). */
export function bitmapLooksUniformBlank(bitmap: Uint8Array): boolean {
  if (bitmap.length < 4) return true
  let min = 255
  let max = 0
  let samples = 0
  const step = Math.max(4, Math.floor(bitmap.length / 480) * 4)
  for (let i = 0; i + 2 < bitmap.length; i += step) {
    const mean = (bitmap[i] + bitmap[i + 1] + bitmap[i + 2]) / 3
    if (mean < min) min = mean
    if (mean > max) max = mean
    samples += 1
  }
  return samples > 0 && max - min < 3 && min >= 230
}

/**
 * Linux/VM Electron drops the GPU front buffer when the window is unmapped.
 * Ctrl+R and a resize then hit a renderer that is no longer presenting frames.
 * Reload from the main process, and do not loop if a second blank arrives immediately.
 */
export function attachRendererSurfaceRecovery(win: BrowserWindow, writeLog: WriteLog): void {
  let lastReloadAt = 0
  let probeTimer: ReturnType<typeof setTimeout> | undefined
  const reloadOnce = (reason: string) => {
    if (win.isDestroyed()) return
    const now = Date.now()
    if (now - lastReloadAt < 3000) {
      writeLog(`[renderer] skip reload; blank frame repeated within 3s (${reason})\n`)
      return
    }
    lastReloadAt = now
    writeLog(`[renderer] reloading in place after ${reason}\n`)
    try {
      win.webContents.reload()
    } catch (error) {
      writeLog(`[renderer] reload failed: ${error instanceof Error ? error.message : String(error)}\n`)
    }
  }
  const probe = () => {
    if (win.isDestroyed()) return
    if (win.isVisible && !win.isVisible()) return
    try {
      win.webContents.invalidate?.()
    } catch {
      /* invalidate is optional across Electron versions */
    }
    const capture = win.webContents.capturePage
    if (!capture) return
    void capture.call(win.webContents).then((image) => {
      if (win.isDestroyed()) return
      if (bitmapLooksUniformBlank(image.toBitmap())) reloadOnce('uniform blank frame after show')
    }).catch((error: unknown) => {
      writeLog(`[renderer] frame probe failed: ${error instanceof Error ? error.message : String(error)}\n`)
      reloadOnce('frame probe failed')
    })
  }
  const scheduleProbe = () => {
    if (probeTimer) clearTimeout(probeTimer)
    probeTimer = setTimeout(probe, 350)
  }
  try {
    win.webContents.setBackgroundThrottling?.(false)
  } catch {
    /* older Electron builds omit this setter */
  }
  win.on('show', scheduleProbe)
  win.on('restore', scheduleProbe)
  win.webContents.on('unresponsive', () => {
    writeLog('[renderer] unresponsive; reloading the page without quitting\n')
    reloadOnce('renderer unresponsive')
  })
  win.webContents.on('before-input-event', (event, input) => {
    const typed = input as Input
    const key = String(typed.key || '').toLowerCase()
    if (typed.type === 'keyDown' && (typed.control || typed.meta) && key === 'r') {
      ;(event as ElectronEvent).preventDefault()
      reloadOnce('Ctrl+R from the main process')
    }
  })
}
