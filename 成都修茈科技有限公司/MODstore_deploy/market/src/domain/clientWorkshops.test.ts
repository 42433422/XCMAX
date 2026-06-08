import { describe, expect, it } from 'vitest'
import {
  CLIENT_WORKSHOPS,
  clientWorkshopNodeId,
  getClientWorkshop,
  listClientWorkshops,
  parseClientWorkshopNodeId,
  parseWbGearQuery,
  resolveClientWorkshopRoute,
  workshopsForArea,
} from './clientWorkshops'

describe('clientWorkshops', () => {
  it('seeds eight enabled workshops', () => {
    expect(CLIENT_WORKSHOPS.length).toBe(8)
    expect(listClientWorkshops().length).toBe(8)
  })

  it('gear workshops use wbGear query on workbench-home', () => {
    for (const gear of ['direct', 'make', 'voice'] as const) {
      const w = getClientWorkshop(`wb-gear-${gear}`)
      expect(w?.kind).toBe('gear')
      const loc = resolveClientWorkshopRoute(w!)
      expect(loc).toMatchObject({
        name: 'workbench-home',
        query: { wbGear: gear },
      })
    }
  })

  it('workshopsForArea links make gear to craft-workshop', () => {
    const linked = workshopsForArea('craft-workshop')
    expect(linked.some((w) => w.id === 'wb-gear-make')).toBe(true)
  })

  it('parseWbGearQuery accepts only direct|make|voice', () => {
    expect(parseWbGearQuery('direct')).toBe('direct')
    expect(parseWbGearQuery('MAKE')).toBe('make')
    expect(parseWbGearQuery('')).toBeNull()
    expect(parseWbGearQuery('chat')).toBeNull()
  })

  it('node id prefix round-trips', () => {
    const nid = clientWorkshopNodeId('wb-unified')
    expect(parseClientWorkshopNodeId(nid)).toBe('wb-unified')
    expect(parseClientWorkshopNodeId('intent-analyst')).toBeNull()
  })

  it('page workshops have unique route names', () => {
    const names = listClientWorkshops()
      .filter((w) => w.kind === 'page')
      .map((w) => w.route?.name)
    expect(new Set(names).size).toBe(names.length)
  })
})
