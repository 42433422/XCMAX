import { describe, expect, it } from 'vitest'
import { applyOfficeActivity, buildOfficeLayout, OfficeState, type OfficeZone } from './pixelOffice'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import { buildDynamicCatalog } from '../../../third_party/pixel-agents/webview-ui/src/office/layout/furnitureCatalog'
const row = (empId: string, state = 'idle') => ({ empId, shortName: empId, panelTitle: empId, enabled: true, snapshot: { officeState: state, progressPct: 100 } } as WorkflowEmployeeDeskRow)
const zone = (id: string, employeeIds: string[]): OfficeZone => ({ id, label: id, color: '#333333', employeeIds })
buildDynamicCatalog({ catalog: [{ id: 'WOODEN_CHAIR_FRONT', label: 'chair', category: 'chairs', width: 16, height: 32, footprintW: 1, footprintH: 2, backgroundTiles: 1, isDesk: false, orientation: 'front' }], sprites: { WOODEN_CHAIR_FRONT: [['#ffffff']] } })
describe('Pixel Agents product adapter', () => {
  it('seats a shared employee once while preserving all configured departments', () => {
    const model = buildOfficeLayout([zone('one', ['a']), zone('two', ['a', 'b']), zone('three', []), zone('four', [])], [row('a'), row('b')])
    expect(model.rooms).toHaveLength(4); expect(model.seats.map(seat => seat.empId)).toEqual(['a', 'b']); expect(model.seats.find(seat => seat.empId === 'a')?.zoneId).toBe('one')
  })
  it('does not invent registered employees or silently relocate unassigned employees', () => {
    const model = buildOfficeLayout([zone('one', ['a', 'unregistered'])], [row('a'), row('unassigned')])
    expect(model.seats.map(seat => seat.empId)).toEqual(['a']); expect(model.unassigned.map(employee => employee.empId)).toEqual(['unassigned'])
  })
  it('animates authoritative states, stops on disconnect, and never wanders across departments', () => {
    const rows = [row('a', 'working'), row('b', 'waiting')]; const model = buildOfficeLayout([zone('one', ['a', 'b'])], rows); const office = new OfficeState(model.layout)
    for (const seat of model.seats) office.addAgent(seat.id, 0, 0, seat.seatId, true)
    applyOfficeActivity(office, model.seats, rows); expect(office.characters.get(1)?.isActive).toBe(true); expect(office.characters.get(2)?.isActive).toBe(false)
    const position = { x: office.characters.get(2)!.x, y: office.characters.get(2)!.y }
    for (let i = 0; i < 600; i++) office.update(1)
    expect(office.characters.get(2)!.x).toBe(position.x); expect(office.characters.get(2)!.y).toBe(position.y)
    applyOfficeActivity(office, model.seats, [row('a', 'offline'), row('b', 'done')]); expect([...office.characters.values()].some(character => character.isActive)).toBe(false); expect(office.characters.get(2)?.bubbleType).toBe('waiting')
  })
  it('does not turn a 100 percent snapshot without runtime state into work or completion', () => {
    const rows = [row('a')]; delete rows[0].snapshot!.officeState; const model = buildOfficeLayout([zone('one', ['a'])], rows); const office = new OfficeState(model.layout)
    office.addAgent(1, 0, 0, model.seats[0].seatId, true); applyOfficeActivity(office, model.seats, rows)
    expect(office.characters.get(1)?.isActive).toBe(false); expect(office.characters.get(1)?.bubbleType).toBeNull()
  })
})
