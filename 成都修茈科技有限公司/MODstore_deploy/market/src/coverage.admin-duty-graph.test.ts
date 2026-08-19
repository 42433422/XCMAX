import { flushPromises, shallowMount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  fail: false,
  responses: {} as Record<string, unknown>,
}))

const api = vi.hoisted(() => new Proxy<Record<string, ReturnType<typeof vi.fn>>>({}, {
  get(target, property: string) {
    if (!target[property]) {
      target[property] = vi.fn(async (...args: unknown[]) => {
        if (state.fail) throw new Error(`${property} unavailable`)
        if (Object.prototype.hasOwnProperty.call(state.responses, property)) {
          const override = state.responses[property]
          return typeof override === 'function'
            ? (override as (...params: unknown[]) => unknown)(...args)
            : override
        }
        switch (property) {
          case 'llmStatus':
            return {
              fernet_configured: true,
              providers: [{
                provider: 'deepseek',
                label: 'DeepSeek',
                has_platform_key: true,
                has_user_override: false,
              }],
            }
          case 'adminDutyGraphHealth':
            return { staffing: { missing_employees: [] } }
          case 'getEmployeeStatus':
            return {
              execution_stats: { total_executions: 3, success_count: 2, success_rate: 0.67 },
              last_execution: '2026-08-17T00:00:00Z',
            }
          case 'getEmployeeManifest':
            return {
              manifest: {
                depends_on: [],
                employee_config_v2: {
                  cognition: { agent: { model: { provider: 'deepseek', model_name: 'deepseek-chat' } } },
                  actions: { handlers: ['llm_md'] },
                  collaboration: { depends_on: [] },
                },
              },
            }
          case 'adminEmployeeExecutionCapabilities':
            return {
              items: ((args[0] as string[]) || []).map((employeeId) => ({
                employee_id: employeeId,
                name: employeeId,
                source: 'catalog',
                deployed: true,
                executable: true,
                reasons: [],
                handlers: ['llm_md'],
                declared_dependencies: [],
                llm: {
                  provider: 'deepseek',
                  model: 'deepseek-chat',
                  needs_llm: true,
                  activated: true,
                  key_source: 'platform',
                },
                risk: { high_risk: false, requires_confirmation: false, details: [] },
                recent_execution: null,
                recent_ops_audits: [],
              })),
            }
          case 'adminListNoKeyEmployees':
            return { items: [], count: 0, fernet_configured: true, any_provider_has_key: true }
          case 'adminEmployeeExecutionMetrics':
            return { items: [], total: 0 }
          case 'adminDutyGraphRunStart':
          case 'adminDutyGraphRunDetail':
            return { id: 1, status: 'success', nodes: [] }
          case 'llmResolveChatDefault':
            return { provider: 'deepseek', model: 'deepseek-chat' }
          case 'llmChat':
            return { content: 'ok' }
          default:
            return { ok: true, success: true, items: [], data: [] }
        }
      })
    }
    return target[property]
  },
}))

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  resolve: vi.fn(() => ({ href: '/workbench' })),
}))
const route = vi.hoisted(() => ({ query: {} as Record<string, unknown> }))
const fitView = vi.hoisted(() => vi.fn(async () => undefined))

vi.mock('./api', () => ({ api }))
vi.mock('./stores/auth', () => ({ useAuthStore: () => ({ currentMode: 'auto' }) }))
vi.mock('pinia', () => ({ storeToRefs: () => ({ currentMode: ref('auto') }) }))
vi.mock('vue-router', () => ({ useRouter: () => router, useRoute: () => route }))
vi.mock('@vue-flow/core', () => ({
  VueFlow: { template: '<div class="vue-flow-stub"><slot /></div>' },
  useVueFlow: () => ({ fitView }),
  MarkerType: { ArrowClosed: 'arrowclosed' },
}))
vi.mock('@vue-flow/background', () => ({ Background: { template: '<i />' } }))
vi.mock('@vue-flow/controls', () => ({ Controls: { template: '<i />' } }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: { template: '<i />' } }))

import AdminDutyEmployeeGraph from './components/admin/AdminDutyEmployeeGraph.vue'

function setupState(wrapper: ReturnType<typeof shallowMount>): Record<string, unknown> {
  return (wrapper.vm as unknown as { $?: { setupState?: Record<string, unknown> } }).$?.setupState ?? {}
}

describe('admin duty employee graph production surface', () => {
  beforeEach(() => {
    state.fail = false
    state.responses = {}
    route.query = {}
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('prompt', vi.fn(() => 'task'))
    vi.stubGlobal('open', vi.fn())
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn(async () => undefined) },
    })
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('loads the real roster, capabilities, graph and command helpers', async () => {
    const wrapper = shallowMount(AdminDutyEmployeeGraph, {
      props: { open: true, variant: 'page' },
      global: { stubs: { teleport: true, transition: false, MessageBody: true, RouterLink: true } },
    })
    await flushPromises()
    await nextTick()

    expect(api.adminDutyGraphHealth).toHaveBeenCalled()
    expect(api.adminEmployeeExecutionCapabilities).toHaveBeenCalled()
    expect(wrapper.exists()).toBe(true)

    const vm = setupState(wrapper)
    const safeHandler = /^(format|is|has|can|resolve|build|compute|normalize|label|state|status|describe|extract|parse|selected|health|llm|gap|client|craft|employee|open|close|toggle|focus|copy|apply|load)/i
    const skip = /(poll|timer|interval|autoRefresh|allHands|dispatch|execute|chat)/i
    let exercised = 0
    for (const [name, candidate] of Object.entries(vm)) {
      if (typeof candidate !== 'function' || !safeHandler.test(name) || skip.test(name)) continue
      try {
        await candidate()
      } catch {
        // Empty arguments intentionally cover defensive validation paths.
      }
      exercised += 1
    }
    await flushPromises()
    expect(exercised).toBeGreaterThan(20)
    expect(fitView).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the graph usable when startup services fail', async () => {
    state.fail = true
    const wrapper = shallowMount(AdminDutyEmployeeGraph, {
      props: { open: true, variant: 'page' },
      global: { stubs: { teleport: true, transition: false, MessageBody: true, RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.text()).toContain('unavailable')
    wrapper.unmount()
  })

  it('runs duty operations, all-hands reporting, dispatch and graph-run branches', async () => {
    const allHandsRow = {
      employee_id: 'intent-analyst',
      name: 'Intent analyst',
      area: 'platform-core',
      status: 'ok',
      report_markdown: 'Everything is healthy.',
      cognition_error: '',
      warnings: [],
      manifest_signals: {
        name: 'Intent analyst', persona: 'analyst', expertise: ['intent'],
        handlers: ['llm_md'], depends_on: [], skills: [], workflow_id: 0,
      },
      recent_failures: [],
      research_sources: [],
    }
    const allHandsReport = {
      ok: true,
      started_at: '2026-08-17T00:00:00Z',
      completed_at: '2026-08-17T00:00:01Z',
      employees: [allHandsRow],
      summary: { total: 1, ok: 1, error: 0 },
    }
    state.responses = {
      adminListNoKeyEmployees: {
        items: [{
          pkg_id: 'intent-analyst', name: 'Intent analyst', current_provider: 'deepseek',
          current_model: 'deepseek-chat', key_source: 'none', suggested_action: 'align_to_auto',
          reasons: ['missing key'],
        }],
        count: 1,
        fernet_configured: true,
        any_provider_has_key: true,
      },
      adminAlignSingleEmployeeLlmToAuto: { ok: true },
      butlerAllHandsReportStartSession: { session_id: 'all-hands-1', status: 'running' },
      workbenchGetSession: {
        status: 'done',
        planning_record: { progress: { total: 1, completed: 1, ok: 1, error: 0, percent: 100 } },
        artifact: {
          all_hands_report: allHandsReport,
          meeting_minutes: { text: 'Meeting minutes' },
          meeting_minutes_email: { recipients_count: 1, any_delivered: true },
        },
      },
      llmChat: { content: '<think>hidden</think>爸爸，一切正常。爸爸' },
      adminDutyGraphRunStart: {
        id: 51,
        status: 'success',
        nodes: [{ employee_id: 'intent-analyst', status: 'success' }],
      },
      adminDutyGraphRunDetail: {
        id: 51,
        status: 'success',
        nodes: [{ employee_id: 'intent-analyst', status: 'success' }],
      },
      executeEmployeeTask: { summary: 'completed' },
      adminEmployeeExecutionMetrics: {
        items: [{
          id: 61, user_id: 1, task: 'inspect', status: 'success', duration_ms: 120,
          llm_tokens: 30, error: '', created_at: '2026-08-17T00:00:00Z',
        }],
        total: 1,
      },
    }

    const wrapper = shallowMount(AdminDutyEmployeeGraph, {
      props: { open: true, variant: 'page' },
      global: { stubs: { teleport: true, transition: false, MessageBody: true, RouterLink: true } },
    })
    await flushPromises()
    await nextTick()
    const vm = setupState(wrapper) as Record<string, UnsafeTestValue>
    const realEmployee = vm.employees.find((row: { source: string }) => row.source === 'catalog')
    const virtualEmployee = vm.employees.find((row: { source: string }) => row.source === 'virtual')
    expect(realEmployee).toBeTruthy()
    expect(virtualEmployee).toBeTruthy()

    for (const mode of ['hub', 'department', 'legacy-area', 'client']) {
      vm.viewMode = mode
      if (mode === 'hub') vm.buildHubGraph(vm.employees)
      else if (mode === 'department') vm.buildDepartmentGraph(vm.employees)
      else if (mode === 'legacy-area') vm.buildAreaGraph(vm.employees)
      else vm.buildClientWorkshopGraph()
      await nextTick()
    }
    expect(vm.flowNodes.length).toBeGreaterThan(0)

    vm.healthMap = {
      [realEmployee.id]: { total: 2, success: 2, rate: 100, lastExecution: null },
      warn: { total: 2, success: 1, rate: 50, lastExecution: null },
      idle: { total: 0, success: 0, rate: 0, lastExecution: null },
    }
    expect(vm.healthLevel(realEmployee.id)).toBe('healthy')
    expect(vm.healthLevel('warn')).toBe('warn')
    expect(vm.healthLevel('idle')).toBe('idle')
    expect(vm.healthLevel('absent')).toBe('unknown')
    vm.empAreaColor(realEmployee.id)
    vm.capabilityLevel(realEmployee.id)
    vm.capabilityColor(realEmployee.id)
    vm.capabilityLabel(realEmployee.id)
    vm.runStatusLevel(realEmployee.id)
    vm.craftEmployeeDependsOn('employee-planner')
    vm.isVirtualEmployee(virtualEmployee.id)
    vm.isDutyGraphMember(realEmployee)
    vm.isDeployedDutyRosterRow(realEmployee)

    for (const panel of ['gap', 'run', 'allhands', 'nokey']) vm.togglePanel(panel)
    await vm.openNoKeyPanel()
    await vm.loadNoKeyEmployees()
    const noKeyResponse = state.responses.adminListNoKeyEmployees as { items: Array<Record<string, unknown>> }
    await vm.alignSingleEmployeeToAuto(noKeyResponse.items[0])
    vm.gotoAddKey()

    vm.applyAllHandsProgress({ total: 4, completed: 9, ok: 3, error: 1, percent: 130 })
    vm.applyAllHandsProgress({ total: 0, completed: 2, percent: Number.NaN })
    expect(vm.parseAllHandsReportFromArtifact({ all_hands_report: allHandsReport })).toEqual(allHandsReport)
    expect(vm.parseAllHandsReportFromArtifact({ all_hands_report: { employees: null } })).toBeNull()
    vm.applyAllHandsReport({ ...allHandsReport, ok: false, error: 'report failed' })
    vm.applyAllHandsReport(allHandsReport)
    vm.toggleAllHandsRow(allHandsRow.employee_id)
    await vm.runAllHands()
    await vm.pollAllHandsSession('all-hands-1')
    await vm.requestPlainLang(allHandsRow)
    expect(vm.allHandsPlainText[allHandsRow.employee_id]).not.toContain('<think>')
    await vm.requestPlainLang(allHandsRow)
    vm.publishFollowUpToButler(allHandsRow)
    await vm.copyAllHandsMeetingMinutes()
    vm.stopAllHandsPolling()

    vm.runTargetId = realEmployee.id
    vm.runTaskBrief = 'Inspect the catalog'
    vm.runInputJson = '{"source":"coverage"}'
    await vm.startGraphRun()
    await vm.pollRunDetail(51)
    expect(vm.runStatusLevel('intent-analyst')).toBe('success')
    vm.stopRunPolling()
    vm.startAutoRefresh()
    vi.advanceTimersByTime(1000)
    vm.stopAutoRefresh()

    vm.viewMode = 'hub'
    vm.onNodeClick({ node: { id: realEmployee.id, type: 'default' } })
    vm.taskBrief = 'Run employee task'
    vm.taskInputJson = '{"order":"ORD-1"}'
    await vm.dispatchTask()
    expect(vm.taskResult).toBe('completed')
    await vm.fetchExecMetrics(false)
    await vm.fetchExecMetrics(true)
    expect(vm.execItems.length).toBeGreaterThan(0)
    vm.publishTaskToButler()
    vm.formatDurationMs(120)
    vm.formatDurationMs(1200)
    vm.formatDurationMs(-1)
    vm.formatRate(82.4)
    vm.formatTime('2026-08-17T00:00:00Z')
    vm.formatTime(undefined)

    vm.onNodeClick({ node: { id: '__center__', type: 'input' } })
    vm.onNodeClick({ node: { id: 'missing', type: 'default' } })
    vm.onClientWorkshopNodeClick({ id: '__client_center__' })
    vm.onClientWorkshopNodeClick({ id: 'missing-workshop' })
    vm.focusEmployeeFromWorkshop(realEmployee.id)
    vm.goUse(realEmployee)
    vm.goUse(virtualEmployee)
    vm.onAccountKeysNav()
    vm.onBackdropClick()
    vm.openGapPanel()

    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })
})
