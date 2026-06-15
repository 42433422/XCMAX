import { describe, it, expect } from 'vitest'
import {
  clientWorkshopNodeId,
  parseClientWorkshopNodeId,
  listClientWorkshops,
  getClientWorkshop,
  resolveClientWorkshopRoute,
  workshopsForArea,
  linkedRosterEmployeeIds,
  parseWbGearQuery,
  CLIENT_WORKSHOP_NODE_PREFIX,
  type ClientWorkshop,
} from './clientWorkshops'

describe('clientWorkshops', () => {
  describe('clientWorkshopNodeId', () => {
    it('prefixes workshop id with node prefix', () => {
      expect(clientWorkshopNodeId('test')).toBe(`${CLIENT_WORKSHOP_NODE_PREFIX}test`)
    })

    it('handles empty string', () => {
      expect(clientWorkshopNodeId('')).toBe(CLIENT_WORKSHOP_NODE_PREFIX)
    })
  })

  describe('parseClientWorkshopNodeId', () => {
    it('extracts workshop id from node id', () => {
      const nodeId = clientWorkshopNodeId('my-workshop')
      expect(parseClientWorkshopNodeId(nodeId)).toBe('my-workshop')
    })

    it('returns null for non-workshop node id', () => {
      expect(parseClientWorkshopNodeId('regular-node')).toBeNull()
    })

    it('returns null for empty string', () => {
      expect(parseClientWorkshopNodeId('')).toBeNull()
    })

    it('returns null for prefix-only string', () => {
      expect(parseClientWorkshopNodeId(CLIENT_WORKSHOP_NODE_PREFIX)).toBeNull()
    })
  })

  describe('listClientWorkshops', () => {
    it('returns only enabled workshops by default', () => {
      const workshops = listClientWorkshops()
      expect(workshops.length).toBeGreaterThan(0)
      workshops.forEach((w) => expect(w.enabled).toBe(true))
    })

    it('returns all workshops including disabled when includeDisabled is true', () => {
      const enabled = listClientWorkshops()
      const all = listClientWorkshops({ includeDisabled: true })
      expect(all.length).toBeGreaterThanOrEqual(enabled.length)
    })

    it('returns a mutable copy', () => {
      const workshops = listClientWorkshops()
      const original = workshops.length
      workshops.push({ id: 'fake', label: 'Fake', kind: 'gear', enabled: true })
      expect(listClientWorkshops()).toHaveLength(original)
    })
  })

  describe('getClientWorkshop', () => {
    it('returns workshop by id', () => {
      const workshop = getClientWorkshop('wb-gear-direct')
      expect(workshop).toBeDefined()
      expect(workshop?.id).toBe('wb-gear-direct')
      expect(workshop?.label).toBe('聊')
      expect(workshop?.kind).toBe('gear')
    })

    it('returns undefined for unknown id', () => {
      expect(getClientWorkshop('nonexistent')).toBeUndefined()
    })
  })

  describe('resolveClientWorkshopRoute', () => {
    it('returns route for workshop with route', () => {
      const workshop = getClientWorkshop('wb-gear-direct')!
      const route = resolveClientWorkshopRoute(workshop)
      expect(route).not.toBeNull()
      expect(route).toEqual({
        name: 'workbench-home',
        query: { wbGear: 'direct' },
      })
    })

    it('returns null for workshop without route', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
      }
      expect(resolveClientWorkshopRoute(workshop)).toBeNull()
    })

    it('returns null for workshop with route but no name', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
        route: { name: '' },
      }
      expect(resolveClientWorkshopRoute(workshop)).toBeNull()
    })

    it('returns route without query when workshop has no query', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
        route: { name: 'some-route' },
      }
      const route = resolveClientWorkshopRoute(workshop)
      expect(route).toEqual({ name: 'some-route', query: undefined })
    })
  })

  describe('workshopsForArea', () => {
    it('returns workshops linked to an area', () => {
      const workshops = workshopsForArea('craft-workshop')
      expect(workshops.length).toBeGreaterThan(0)
      workshops.forEach((w) => expect(w.linkedAreaId).toBe('craft-workshop'))
    })

    it('returns empty array for unknown area', () => {
      expect(workshopsForArea('nonexistent')).toHaveLength(0)
    })
  })

  describe('linkedRosterEmployeeIds', () => {
    it('returns linkedEmployeeIds when present', () => {
      const workshop = getClientWorkshop('wb-gear-direct')!
      const ids = linkedRosterEmployeeIds(workshop)
      expect(Array.isArray(ids)).toBe(true)
      expect(ids.length).toBeGreaterThan(0)
    })

    it('returns area ids when no linkedEmployeeIds', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
        linkedAreaId: 'craft-workshop',
      }
      const ids = linkedRosterEmployeeIds(workshop)
      expect(ids.length).toBeGreaterThan(0)
    })

    it('returns empty array when no linkedEmployeeIds and no linkedAreaId', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
      }
      expect(linkedRosterEmployeeIds(workshop)).toEqual([])
    })

    it('returns empty array when linkedAreaId is unknown', () => {
      const workshop: ClientWorkshop = {
        id: 'test',
        label: 'Test',
        kind: 'gear',
        enabled: true,
        linkedAreaId: 'nonexistent-area',
      }
      expect(linkedRosterEmployeeIds(workshop)).toEqual([])
    })

    it('returns a copy of linkedEmployeeIds', () => {
      const workshop = getClientWorkshop('wb-gear-direct')!
      const ids1 = linkedRosterEmployeeIds(workshop)
      const ids2 = linkedRosterEmployeeIds(workshop)
      expect(ids1).not.toBe(ids2)
      expect(ids1).toEqual(ids2)
    })
  })

  describe('parseWbGearQuery', () => {
    it('parses valid gear values', () => {
      expect(parseWbGearQuery('direct')).toBe('direct')
      expect(parseWbGearQuery('make')).toBe('make')
      expect(parseWbGearQuery('voice')).toBe('voice')
    })

    it('is case-insensitive', () => {
      expect(parseWbGearQuery('Direct')).toBe('direct')
      expect(parseWbGearQuery('MAKE')).toBe('make')
      expect(parseWbGearQuery('Voice')).toBe('voice')
    })

    it('trims whitespace', () => {
      expect(parseWbGearQuery('  direct  ')).toBe('direct')
    })

    it('returns null for invalid values', () => {
      expect(parseWbGearQuery('invalid')).toBeNull()
      expect(parseWbGearQuery('')).toBeNull()
    })

    it('returns null for null/undefined', () => {
      expect(parseWbGearQuery(null)).toBeNull()
      expect(parseWbGearQuery(undefined)).toBeNull()
    })

    it('returns null for numeric input', () => {
      expect(parseWbGearQuery(123)).toBeNull()
    })
  })
})
