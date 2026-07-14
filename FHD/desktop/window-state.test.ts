import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { clampWindowBounds, readWindowState, writeWindowState } from './window-state'

const files: string[] = []

afterEach(() => {
  for (const file of files.splice(0)) {
    try { fs.rmSync(file, { force: true }) } catch { /* ignore */ }
  }
})

describe('window state', () => {
  it('round-trips an atomic state file', () => {
    const file = path.join(os.tmpdir(), `xcagi-window-${Date.now()}-${Math.random()}.json`)
    files.push(file)
    const bounds = { x: 120, y: 80, width: 1440, height: 900 }
    writeWindowState(file, bounds)
    expect(readWindowState(file)).toEqual(bounds)
  })

  it('rejects corrupted and implausibly small state', () => {
    const file = path.join(os.tmpdir(), `xcagi-window-bad-${Date.now()}-${Math.random()}.json`)
    files.push(file)
    fs.writeFileSync(file, '{bad', 'utf8')
    expect(readWindowState(file)).toBeNull()
    fs.writeFileSync(file, JSON.stringify({ x: 0, y: 0, width: 10, height: 10 }), 'utf8')
    expect(readWindowState(file)).toBeNull()
  })

  it('brings an off-screen window back into the current work area', () => {
    const clamped = clampWindowBounds(
      { x: 5000, y: -3000, width: 2000, height: 1400 },
      { x: 0, y: 25, width: 1280, height: 775 },
    )
    expect(clamped).toEqual({ x: 0, y: 25, width: 1280, height: 775 })
  })
})
