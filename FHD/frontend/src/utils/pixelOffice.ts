import { OfficeState } from '../../../third_party/pixel-agents/webview-ui/src/office/engine/officeState'
import { renderFrame } from '../../../third_party/pixel-agents/webview-ui/src/office/engine/renderer'
import { startGameLoop } from '../../../third_party/pixel-agents/webview-ui/src/office/engine/gameLoop'
import { buildDynamicCatalog } from '../../../third_party/pixel-agents/webview-ui/src/office/layout/furnitureCatalog'
import { setCharacterTemplates } from '../../../third_party/pixel-agents/webview-ui/src/office/sprites/spriteData'
import { setFloorSprites } from '../../../third_party/pixel-agents/webview-ui/src/office/floorTiles'
import { setWallSprites } from '../../../third_party/pixel-agents/webview-ui/src/office/wallTiles'
import { setProviderCapabilities } from '../../../third_party/pixel-agents/webview-ui/src/office/toolUtils'
import { sheetToDirectionSprites } from '../../../third_party/pixel-agents/core/src/assets/characterSheet'
import { rgbaToHex } from '../../../third_party/pixel-agents/core/src/assets/colorUtils'
import { CharacterState, TILE_SIZE, TileType, type OfficeLayout, type SpriteData } from '../../../third_party/pixel-agents/webview-ui/src/office/types'
import atlas from '../../../third_party/pixel-agents/atlas.json'
import atlasUrl from '../../../third_party/pixel-agents/atlas.png'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'

export { OfficeState, renderFrame, startGameLoop, TILE_SIZE }
export type OfficeZone = { id: string; label: string; color: string; employeeIds: string[]; detail?: string }
export type OfficeSeat = { empId: string; id: number; seatId: string; col: number; row: number; zoneId: string }
type Rect = { x: number; y: number; width: number; height: number }
let assetsReady: Promise<void> | null = null

/** One local sprite atlas, decoded once; no external services or telemetry. */
export function loadOfficeAssets(): Promise<void> {
  if (assetsReady) return assetsReady
  assetsReady = (async () => {
    const image = new Image()
    image.src = atlasUrl
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = image.width
    canvas.height = image.height
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) throw new Error('当前设备无法创建办公室画布')
    ctx.drawImage(image, 0, 0)
    const rects = atlas.rects as Record<string, Rect>
    const pixels = (rect: Rect) => ctx.getImageData(rect.x, rect.y, rect.width, rect.height).data
    const sprite = (rect: Rect): SpriteData => {
      const data = pixels(rect)
      return Array.from({ length: rect.height }, (_, y) => Array.from({ length: rect.width }, (_, x) => {
        const i = (y * rect.width + x) * 4
        return rgbaToHex(data[i], data[i + 1], data[i + 2], data[i + 3])
      }))
    }
    setCharacterTemplates(Array.from({ length: 6 }, (_, i) => {
      const rect = rects[`character-${i}`]
      return sheetToDirectionSprites(pixels(rect), rect.width)
    }))
    buildDynamicCatalog({ catalog: atlas.catalog, sprites: Object.fromEntries(atlas.catalog.map(item => [item.id, sprite(rects[item.id])])) })
    setFloorSprites([sprite(rects.floor)])
    setWallSprites([Array.from({ length: 16 }, (_, i) => sprite({ x: rects.wall.x + i % 4 * 16, y: rects.wall.y + Math.floor(i / 4) * 32, width: 16, height: 32 }))])
    setProviderCapabilities({ readingTools: ['Read'], subagentToolNames: [] })
  })().catch(error => { assetsReady = null; throw error })
  return assetsReady
}

/** Stable SSOT order gives shared employees one physical seat, with shared selection. */
export function buildOfficeLayout(zones: OfficeZone[], desks: WorkflowEmployeeDeskRow[]) {
  const ids = new Set(desks.map(row => row.empId))
  const assigned = new Set<string>()
  const groups = zones.map(zone => ({ ...zone, members: zone.employeeIds.filter(id => {
    if (!ids.has(id) || assigned.has(id)) return false
    assigned.add(id)
    return true
  }) }))
  const roomCols = 24, gap = 3, gridCols = Math.min(2, Math.max(1, groups.length))
  const rowHeights = Array.from({ length: Math.ceil(groups.length / gridCols) }, (_, row) =>
    Math.max(...groups.slice(row * gridCols, (row + 1) * gridCols).map(g => 6 + Math.max(1, Math.ceil(g.members.length / 4)) * 6)))
  const cols = gridCols * (roomCols + gap) + 1
  const rows = rowHeights.reduce((sum, height) => sum + height + gap, 1)
  const layout: OfficeLayout = { version: 1, cols, rows, tiles: Array(cols * rows).fill(TileType.VOID), tileColors: Array(cols * rows).fill(null), furniture: [] }
  const seats: OfficeSeat[] = []
  const rooms: Array<OfficeZone & { col: number; row: number; count: number; width: number }> = []
  groups.forEach((group, index) => {
    const gridRow = Math.floor(index / gridCols)
    const left = 1 + index % gridCols * (roomCols + gap)
    const top = 1 + rowHeights.slice(0, gridRow).reduce((sum, height) => sum + height + gap, 0)
    const height = rowHeights[gridRow]
    rooms.push({ ...group, col: left, row: top, count: group.members.length, width: roomCols })
    for (let row = top; row < top + height; row++) for (let col = left; col < left + roomCols; col++) {
      const wall = row === top || col === left || col === left + roomCols - 1
      layout.tiles[row * cols + col] = wall ? TileType.WALL : TileType.FLOOR_1
      layout.tileColors![row * cols + col] = wall ? { h: 30, s: 14, b: 1, c: 0 } : { h: index % 2 ? 28 : 36, s: 20, b: 16, c: -15 }
    }
    layout.furniture.push({ uid: `${group.id}:plant`, type: 'PLANT', col: left + roomCols - 3, row: top + 1 })
    group.members.forEach((empId, i) => {
      const col = left + 2 + i % 4 * 5, row = top + 4 + Math.floor(i / 4) * 6
      const seatId = `seat:${empId}`
      seats.push({ empId, id: desks.findIndex(d => d.empId === empId) + 1, seatId, col: col + 1, row: row + 1, zoneId: group.id })
      layout.furniture.push(
        { uid: seatId, type: 'WOODEN_CHAIR_FRONT', col: col + 1, row },
        { uid: `desk:${empId}`, type: 'DESK_FRONT', col, row: row + 1 },
        { uid: `pc:${empId}`, type: 'PC_BACK', col: col + 1, row: row + 1 },
      )
    })
  })
  return { layout, seats, rooms, unassigned: desks.filter(d => !assigned.has(d.empId)) }
}

/** The upstream engine animates only the task projection, never synthesizes work. */
export function applyOfficeActivity(office: OfficeState, seats: OfficeSeat[], desks: WorkflowEmployeeDeskRow[]) {
  const byId = new Map(desks.map(row => [row.empId, row]))
  for (const seat of seats) {
    const row = byId.get(seat.empId)
    const state = row?.snapshot?.officeState ?? 'offline'
    const active = state === 'working' || state === 'reading'
    const character = office.characters.get(seat.id)
    if (!character) continue
    if (character.isActive !== active) office.setAgentActive(seat.id, active)
    office.setAgentTool(seat.id, state === 'reading' ? 'Read' : null)
    // Keep seats in their actual department. No upstream random idle wandering.
    character.state = CharacterState.TYPE
    character.seatTimer = Infinity
    character.wanderTimer = Infinity
    character.path = []
    character.bubbleType = state === 'waiting' ? 'permission' : state === 'done' ? 'waiting' : null
    character.bubbleTimer = Infinity
  }
}
