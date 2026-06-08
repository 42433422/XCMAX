import { describe, expect, it } from 'vitest'
import {
  AGENT_ACTIONS,
  validateNavigateArgs,
  ROUTE_NAME_MAP,
  ACTION_RISKS,
} from './agentActionTypes'

describe('AGENT_ACTIONS', () => {
  it('has expected action types', () => {
    expect(AGENT_ACTIONS.NAVIGATE).toBe('navigate')
    expect(AGENT_ACTIONS.CLICK).toBe('click')
    expect(AGENT_ACTIONS.FILL).toBe('fill')
    expect(AGENT_ACTIONS.SELECT).toBe('select')
    expect(AGENT_ACTIONS.SCROLL).toBe('scroll')
    expect(AGENT_ACTIONS.READ).toBe('read')
    expect(AGENT_ACTIONS.PURCHASE).toBe('purchase')
    expect(AGENT_ACTIONS.RECHARGE).toBe('recharge')
    expect(AGENT_ACTIONS.SEARCH_EMPLOYEE).toBe('search_employee')
  })
})

describe('validateNavigateArgs', () => {
  it('validates correct navigate args', () => {
    expect(validateNavigateArgs({ route: '/home' })).toBe(true)
  })

  it('rejects null', () => {
    expect(validateNavigateArgs(null)).toBe(false)
  })

  it('rejects undefined', () => {
    expect(validateNavigateArgs(undefined)).toBe(false)
  })

  it('rejects non-object', () => {
    expect(validateNavigateArgs('string')).toBe(false)
  })

  it('rejects missing route', () => {
    expect(validateNavigateArgs({})).toBe(false)
  })

  it('rejects empty route', () => {
    expect(validateNavigateArgs({ route: '' })).toBe(false)
  })

  it('accepts route with params and query', () => {
    expect(validateNavigateArgs({ route: '/test', params: {}, query: {} })).toBe(true)
  })
})

describe('ROUTE_NAME_MAP', () => {
  it('maps Chinese names to routes', () => {
    expect(ROUTE_NAME_MAP['会员']).toBe('plans')
    expect(ROUTE_NAME_MAP['钱包']).toBe('wallet')
    expect(ROUTE_NAME_MAP['充值']).toBe('recharge')
    expect(ROUTE_NAME_MAP['设置']).toBe('account')
    expect(ROUTE_NAME_MAP['工作台']).toBe('workbench-shell')
    expect(ROUTE_NAME_MAP['首页']).toBe('workbench-home')
    expect(ROUTE_NAME_MAP['客服']).toBe('customer-service')
    expect(ROUTE_NAME_MAP['订单']).toBe('orders')
    expect(ROUTE_NAME_MAP['AI市场']).toBe('ai-store')
  })

  it('maps English names to routes', () => {
    expect(ROUTE_NAME_MAP['plans']).toBe('plans')
    expect(ROUTE_NAME_MAP['wallet']).toBe('wallet')
    expect(ROUTE_NAME_MAP['store']).toBe('ai-store')
    expect(ROUTE_NAME_MAP['home']).toBe('workbench-home')
  })
})

describe('ACTION_RISKS', () => {
  it('assigns low risk to safe actions', () => {
    expect(ACTION_RISKS[AGENT_ACTIONS.NAVIGATE]).toBe('low')
    expect(ACTION_RISKS[AGENT_ACTIONS.READ]).toBe('low')
    expect(ACTION_RISKS[AGENT_ACTIONS.SCROLL]).toBe('low')
    expect(ACTION_RISKS[AGENT_ACTIONS.SEARCH_EMPLOYEE]).toBe('low')
  })

  it('assigns medium risk to interactive actions', () => {
    expect(ACTION_RISKS[AGENT_ACTIONS.CLICK]).toBe('medium')
    expect(ACTION_RISKS[AGENT_ACTIONS.FILL]).toBe('medium')
    expect(ACTION_RISKS[AGENT_ACTIONS.SELECT]).toBe('medium')
  })

  it('assigns high risk to financial actions', () => {
    expect(ACTION_RISKS[AGENT_ACTIONS.PURCHASE]).toBe('high')
    expect(ACTION_RISKS[AGENT_ACTIONS.RECHARGE]).toBe('high')
  })

  it('covers all agent actions', () => {
    const actionValues = Object.values(AGENT_ACTIONS)
    const riskKeys = Object.keys(ACTION_RISKS)
    expect(riskKeys).toHaveLength(actionValues.length)
    for (const action of actionValues) {
      expect(ACTION_RISKS[action as keyof typeof ACTION_RISKS]).toBeDefined()
    }
  })
})
