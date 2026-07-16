import fs from 'node:fs'

export type WindowBounds = { x: number; y: number; width: number; height: number }

export const DEFAULT_WINDOW_BOUNDS: WindowBounds = {
  x: 80,
  y: 60,
  width: 1440,
  height: 920,
}

function finiteInteger(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}

export function readWindowState(filePath: string): WindowBounds | null {
  try {
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as Partial<WindowBounds>
    const x = finiteInteger(raw.x)
    const y = finiteInteger(raw.y)
    const width = finiteInteger(raw.width)
    const height = finiteInteger(raw.height)
    if (x === null || y === null || width === null || height === null) return null
    if (width < 320 || height < 240) return null
    return { x, y, width, height }
  } catch {
    return null
  }
}

export function clampWindowBounds(
  saved: WindowBounds | null,
  workArea: WindowBounds,
  minimum = { width: 1180, height: 760 },
): WindowBounds {
  const source = saved || DEFAULT_WINDOW_BOUNDS
  const width = Math.min(Math.max(source.width, minimum.width), workArea.width)
  const height = Math.min(Math.max(source.height, minimum.height), workArea.height)
  const maxX = workArea.x + workArea.width - width
  const maxY = workArea.y + workArea.height - height
  const x = Math.min(Math.max(source.x, workArea.x), maxX)
  const y = Math.min(Math.max(source.y, workArea.y), maxY)
  return { x, y, width, height }
}

export function writeWindowState(filePath: string, bounds: WindowBounds): void {
  const tempPath = `${filePath}.tmp`
  try {
    fs.writeFileSync(tempPath, `${JSON.stringify(bounds)}\n`, 'utf8')
    fs.renameSync(tempPath, filePath)
  } catch {
    try { fs.rmSync(tempPath, { force: true }) } catch { /* ignore */ }
  }
}
