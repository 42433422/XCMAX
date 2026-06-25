import { describe, it, expect, beforeEach } from 'vitest'
import {
  PLANNER_FACADE_MOD_ID,
  LS_PLANNER_MOD_FACADE_ENABLED,
  readPlannerModFacadeEnabled,
  setPlannerModFacadeEnabled,
} from './plannerMod'

describe('plannerMod constants and functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('PLANNER_FACADE_MOD_ID', () => {
    it('is the planner bridge mod id', () => {
      expect(PLANNER_FACADE_MOD_ID).toBe('xcagi-planner-bridge')
    })
  })

  describe('LS_PLANNER_MOD_FACADE_ENABLED', () => {
    it('is the localStorage key string', () => {
      expect(LS_PLANNER_MOD_FACADE_ENABLED).toBe('xcagi_planner_mod_facade_enabled')
    })
  })

  describe('readPlannerModFacadeEnabled', () => {
    it('returns false when localStorage is empty', () => {
      expect(readPlannerModFacadeEnabled()).toBe(false)
    })

    it('returns false when value is 0', () => {
      localStorage.setItem(LS_PLANNER_MOD_FACADE_ENABLED, '0')
      expect(readPlannerModFacadeEnabled()).toBe(false)
    })

    it('returns true when value is 1', () => {
      localStorage.setItem(LS_PLANNER_MOD_FACADE_ENABLED, '1')
      expect(readPlannerModFacadeEnabled()).toBe(true)
    })

    it('returns false for arbitrary string', () => {
      localStorage.setItem(LS_PLANNER_MOD_FACADE_ENABLED, 'active')
      expect(readPlannerModFacadeEnabled()).toBe(false)
    })
  })

  describe('setPlannerModFacadeEnabled', () => {
    it('sets value to 1 when true', () => {
      setPlannerModFacadeEnabled(true)
      expect(localStorage.getItem(LS_PLANNER_MOD_FACADE_ENABLED)).toBe('1')
    })

    it('sets value to 0 when false', () => {
      setPlannerModFacadeEnabled(false)
      expect(localStorage.getItem(LS_PLANNER_MOD_FACADE_ENABLED)).toBe('0')
    })

    it('read reflects write', () => {
      setPlannerModFacadeEnabled(true)
      expect(readPlannerModFacadeEnabled()).toBe(true)
      setPlannerModFacadeEnabled(false)
      expect(readPlannerModFacadeEnabled()).toBe(false)
    })
  })
})
