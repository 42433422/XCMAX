import type { BrowserWindow, Event as ElectronEvent, Input } from 'electron'

type WriteLog = (line: string) => void

/** A compositor that lost its GL buffer paints one near-white color (std ≈ 0). */
export function bitmapLooksUniformBlank(bitmap: Uint8Array): boolean {
  if (bitmap.length < 4) return false
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
 * Automatic recovery requires a previously painted page, two blank samples and
 * a completed navigation. It may reload only once during this window's lifetime.
 */
export function attachRendererSurfaceRecovery(win: BrowserWindow, writeLog: WriteLog, platform = process.platform): void {
  let lastReloadAt = -Infinity
  let probeTimer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let closed = false
  let loaded = false
  let painted = false
  let blankSamples = 0
  let recovered = false
  const cancelProbe = () => {
    generation += 1
    clearTimeout(probeTimer)
    probeTimer = undefined
    blankSamples = 0
  }
  const reloadOnce = (reason: string) => {
    if (closed || win.isDestroyed()) return
    const now = Date.now()
    if (now - lastReloadAt < 3000) {
      writeLog(`[renderer] skip reload; blank frame repeated within 3s (${reason})\n`)
      return
    }
    lastReloadAt = now
    cancelProbe()
    loaded = false
    writeLog(`[renderer] reloading in place after ${reason}\n`)
    try {
      win.webContents.reload()
    } catch (error) {
      writeLog(`[renderer] reload failed: ${error instanceof Error ? error.message : String(error)}\n`)
    }
  }
  const canProbe = () => !closed && !win.isDestroyed() && loaded
    && !win.webContents.isLoadingMainFrame() && win.isVisible()
  const probe = () => {
    probeTimer = undefined
    if (!canProbe()) return
    const epoch = generation
    try {
      win.webContents.invalidate?.()
    } catch {
      /* invalidate is optional across Electron versions */
    }
    const capture = win.webContents.capturePage
    if (!capture) return
    void Promise.resolve().then(() => capture.call(win.webContents)).then((image) => {
      if (epoch !== generation || !canProbe()) return
      const bitmap = image.toBitmap()
      if (bitmap.length < 4) { blankSamples = 0; return }
      if (!bitmapLooksUniformBlank(bitmap)) { painted = true; blankSamples = 0; return }
      if (!painted || recovered) return
      if (++blankSamples < 2) { scheduleProbe(); return }
      recovered = true
      reloadOnce('confirmed blank frame after show')
    }).catch((error: unknown) => {
      if (epoch !== generation || !canProbe()) return
      blankSamples = 0
      writeLog(`[renderer] frame probe failed: ${error instanceof Error ? error.message : String(error)}\n`)
    })
  }
  const scheduleProbe = () => {
    if (platform !== 'linux' || !canProbe()) return
    clearTimeout(probeTimer)
    probeTimer = setTimeout(probe, 350)
  }
  try {
    win.webContents.setBackgroundThrottling?.(false)
  } catch {
    /* older Electron builds omit this setter */
  }
  const onShow = () => { cancelProbe(); scheduleProbe() }
  win.on('show', onShow)
  win.on('restore', onShow)
  win.on('hide', cancelProbe)
  win.on('minimize', cancelProbe)
  win.on('closed', () => { closed = true; cancelProbe() })
  win.webContents.on('did-start-loading', () => { loaded = false; painted = false; cancelProbe() })
  win.webContents.on('did-finish-load', () => { loaded = true; scheduleProbe() })
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
