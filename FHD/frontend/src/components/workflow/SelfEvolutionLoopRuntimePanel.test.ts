import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'

// Mock 外部边界：API 调用
const statusMock = vi.fn()
const reviewMock = vi.fn()
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: {
    selfMaintenanceRuntimeStatus: (...a: unknown[]) => statusMock(...a),
    selfMaintenanceGovernanceReview: (...a: unknown[]) => reviewMock(...a),
  },
}))

import SelfEvolutionLoopRuntimePanel from './SelfEvolutionLoopRuntimePanel.vue'

// 构造测试 router，包含组件依赖的路由名
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div/>' } },
      { path: '/duty-roster', name: 'duty-roster-graph', component: { template: '<div/>' } },
      { path: '/workspace', name: 'workflow-employee-space', component: { template: '<div/>' } },
    ],
  })
}

function mountComponent(propsOverrides: Record<string, unknown> = {}) {
  const router = makeRouter()
  return mount(SelfEvolutionLoopRuntimePanel, {
    props: {
      compact: false,
      surface: 'employee-space',
      ...propsOverrides,
    },
    global: {
      plugins: [router],
      stubs: {
        // router-link 渲染为普通元素，避免路由解析
        'router-link': { template: '<a><slot/></a>' },
      },
    },
  })
}

describe('SelfEvolutionLoopRuntimePanel.vue', () => {
  beforeEach(() => {
    statusMock.mockReset()
    reviewMock.mockReset()
    statusMock.mockResolvedValue({})
  })

  it('挂载并渲染根 section 与标题', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp').exists()).toBe(true)
    expect(wrapper.find('.selp-title').text()).toContain('系统自动维护状态')
  })

  it('默认 props 为 compact=false / surface=employee-space', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp--compact').exists()).toBe(false)
    // 非 compact 时渲染底部策略区
    expect(wrapper.find('.selp-bottom').exists()).toBe(true)
  })

  it('compact=true 时不渲染底部策略区并加上 compact class', async () => {
    const wrapper = mountComponent({ compact: true })
    await flushPromises()
    expect(wrapper.find('.selp--compact').exists()).toBe(true)
    expect(wrapper.find('.selp-bottom').exists()).toBe(false)
  })

  it('surface=duty-roster 时 runtimeSurfaceKey 解析为 duty_roster_graph', async () => {
    const wrapper = mountComponent({ surface: 'duty-roster' })
    await flushPromises()
    // 模块就绪卡片应展示 duty_roster_graph 相关文案
    const text = wrapper.text()
    expect(text).toContain('模块就绪')
  })

  it('加载中时刷新按钮显示"刷新中"且 disabled', async () => {
    // 让 statusMock 不立即 resolve，保持 loading
    statusMock.mockReturnValue(new Promise(() => {}))
    const wrapper = mountComponent()
    await flushPromises()
    const btn = wrapper.find('.selp-refresh')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.text()).toContain('刷新中')
  })

  it('加载完成后刷新按钮显示"刷新"', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    const btn = wrapper.find('.selp-refresh')
    expect(btn.attributes('disabled')).toBeUndefined()
    expect(btn.text()).toBe('刷新')
  })

  it('API 抛错时显示 error 文案且 statusTone=bad', async () => {
    statusMock.mockRejectedValue(new Error('网络异常'))
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-error').exists()).toBe(true)
    expect(wrapper.find('.selp-error').text()).toContain('网络异常')
    expect(wrapper.find('.selp').classes()).toContain('selp--bad')
    expect(wrapper.find('.selp-state strong').text()).toBe('接口异常')
  })

  it('点击刷新按钮触发 refresh 并重新调用 API', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(statusMock).toHaveBeenCalledTimes(1)
    await wrapper.find('.selp-refresh').trigger('click')
    await flushPromises()
    expect(statusMock).toHaveBeenCalledTimes(2)
  })

  it('compact 模式调用 API 传 limit=40', async () => {
    statusMock.mockResolvedValue({})
    mountComponent({ compact: true })
    await flushPromises()
    expect(statusMock).toHaveBeenCalledWith(40)
  })

  it('非 compact 模式调用 API 传 limit=80', async () => {
    statusMock.mockResolvedValue({})
    mountComponent({ compact: false })
    await flushPromises()
    expect(statusMock).toHaveBeenCalledWith(80)
  })

  it('空数据时状态为待命 (idle)', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp').classes()).toContain('selp--idle')
    expect(wrapper.find('.selp-state strong').text()).toBe('待命')
  })

  it('有 open_run_ids 时状态为运行中', async () => {
    statusMock.mockResolvedValue({
      evidence: { open_run_ids: ['run-1', 'run-2'] },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp').classes()).toContain('selp--running')
    expect(wrapper.find('.selp-state strong').text()).toBe('运行中')
  })

  it('gate.should_run=true 时状态为达到触发阈值 (warn)', async () => {
    statusMock.mockResolvedValue({
      current_gate: { should_run: true, reason: 'threshold' },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp').classes()).toContain('selp--warn')
    expect(wrapper.find('.selp-state strong').text()).toBe('达到触发阈值')
  })

  it('gate.reason=cooldown 时状态为冷却中', async () => {
    statusMock.mockResolvedValue({
      current_gate: { should_run: false, reason: 'cooldown' },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-state strong').text()).toBe('冷却中')
  })

  it('latest_complete.phase=complete 时状态为最近完成 (ok)', async () => {
    statusMock.mockResolvedValue({
      evidence: { latest_complete: { phase: 'complete' } },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp').classes()).toContain('selp--ok')
    expect(wrapper.find('.selp-state strong').text()).toBe('最近完成')
  })

  it('渲染每日调度 cronLine', async () => {
    statusMock.mockResolvedValue({
      cron: { hour: 14, minute: 30, timezone: 'UTC' },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-meta-card strong').text()).toBe('14:30 UTC')
  })

  it('cron 缺失时回退到 03:00 Asia/Shanghai', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-meta-card strong').text()).toBe('03:00 Asia/Shanghai')
  })

  it('有 participants 时渲染参与员工泳道', async () => {
    statusMock.mockResolvedValue({
      participants: [
        { employee_id: 'emp-001', role_label: '侦察', stage_labels: ['sense'] },
        { employee_id: 'emp-002', role_label: '修复', stages: ['repair'] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    const chips = wrapper.findAll('.selp-team-chip')
    expect(chips.length).toBe(2)
    expect(chips[0].find('strong').text()).toBe('emp-001')
  })

  it('无 participants 时渲染空态文案', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-team-empty').exists()).toBe(true)
  })

  it('有 run_timelines 时渲染运行时间线', async () => {
    statusMock.mockResolvedValue({
      run_timelines: [
        {
          run_id: 'run-99',
          open: true,
          items: [
            { phase: 'sense', step: 'scan', label: '扫描证据', status: 'done' },
            { phase: 'repair', step: 'fix', label: '修复代码', status: 'running' },
          ],
        },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-timeline').exists()).toBe(true)
    expect(wrapper.find('.selp-timeline-head strong').text()).toContain('run-99')
    expect(wrapper.find('.selp-timeline-head strong').text()).toContain('运行中')
    const items = wrapper.findAll('.selp-timeline-item')
    expect(items.length).toBe(2)
  })

  it('无 run_timelines 时不渲染时间线', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-timeline').exists()).toBe(false)
  })

  it('渲染 loopStages 六阶段流水线', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    const stages = wrapper.findAll('.selp-stage')
    expect(stages.length).toBe(6)
    expect(stages[0].find('.selp-stage-title').text()).toBe('信号感知')
  })

  it('渲染 decisionCards 决策卡片', async () => {
    statusMock.mockResolvedValue({
      merge_decision: { action: 'merge', reason: 'low risk' },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-decision-card')
    expect(cards.length).toBeGreaterThanOrEqual(1)
    expect(cards[0].find('strong').text()).toBe('merge')
  })

  it('渲染 kbCards 知识库卡片', async () => {
    statusMock.mockResolvedValue({
      kb_summary: {
        redisvl_status: { ready: true, reason: 'index ok' },
        fix_hit_count: 3,
        pattern_hit_count: 5,
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-kb-card')
    expect(cards.length).toBe(3)
    expect(cards[0].find('strong').text()).toBe('就绪')
    expect(cards[1].find('strong').text()).toBe('3')
  })

  it('有 kb 命中时渲染命中列表', async () => {
    statusMock.mockResolvedValue({
      kb_summary: {
        top_fix_hits: [{ symptom: '崩溃', root_cause: '空指针', path: '/a.py' }],
        top_pattern_hits: [{ summary: '模式A', pattern: 'P1', path: '/b.py' }],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-kb-hits').exists()).toBe(true)
    expect(wrapper.findAll('.selp-kb-hits li').length).toBe(2)
    // 详情区
    expect(wrapper.findAll('.selp-kb-detail').length).toBe(2)
  })

  it('渲染 proactiveCards 主动优化卡片', async () => {
    statusMock.mockResolvedValue({
      current_gate: {
        proactive_signals: {
          candidates: [{ title: '优化A', task_type: 'perf' }],
          source: 'scanner',
        },
        proactive_task_count: 1,
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-proactive-card')
    expect(cards.length).toBe(3)
    expect(cards[0].find('strong').text()).toBe('1')
    // 候选列表
    expect(wrapper.find('.selp-proactive-list').exists()).toBe(true)
    expect(wrapper.findAll('.selp-proactive-list li').length).toBe(1)
  })

  it('渲染 evolutionMetricCards 进化指标卡片', async () => {
    statusMock.mockResolvedValue({
      evolution_metrics_summary: {
        pause: false,
        reason: 'ok',
        history_count: 10,
        windows: [{ from_week: 'W1', to_week: 'W2', coverage_delta: 1.5, passed_delta: 5, debt_delta: -10 }],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-metrics-card')
    expect(cards.length).toBe(4)
    expect(cards[0].find('strong').text()).toBe('允许运行')
    // 窗口列表
    expect(wrapper.find('.selp-metrics-windows').exists()).toBe(true)
  })

  it('evolution_metrics pause=true 时显示暂停', async () => {
    statusMock.mockResolvedValue({
      evolution_metrics_summary: { pause: true, reason: 'debt too high' },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-metrics-card')
    expect(cards[0].find('strong').text()).toBe('暂停')
    expect(cards[0].classes()).toContain('selp-metrics-card--bad')
  })

  it('渲染 rosterAlignmentCards 排班匹配卡片', async () => {
    statusMock.mockResolvedValue({
      roster_alignment: {
        planned_count: 54,
        in_roster_count: 10,
        in_deployed_count: 8,
        out_of_roster_count: 0,
        not_deployed_count: 2,
        not_deployed_ids: ['emp-x'],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const cards = wrapper.findAll('.selp-roster-card')
    expect(cards.length).toBe(7)
    expect(cards[0].find('strong').text()).toBe('54')
  })

  it('有 roster remediation 时渲染修复指引', async () => {
    statusMock.mockResolvedValue({
      roster_alignment: {
        remediation: {
          action: 'onboard',
          title: '补登记',
          detail: '需要登记上岗',
          target_employee_ids: ['emp-1', 'emp-2'],
        },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-roster-remediation').exists()).toBe(true)
    expect(wrapper.find('.selp-roster-remediation strong').text()).toBe('补登记')
  })

  it('remediation.action=none 时不渲染修复指引', async () => {
    statusMock.mockResolvedValue({
      roster_alignment: { remediation: { action: 'none' } },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-roster-remediation').exists()).toBe(false)
  })

  it('有 department_coverage 时渲染部门覆盖列表', async () => {
    statusMock.mockResolvedValue({
      roster_alignment: {
        department_coverage: [
          { key: 'tools', label: '工具层', count: 5, total: 10, ids: ['a', 'b'] },
        ],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-roster-coverage').exists()).toBe(true)
    expect(wrapper.findAll('.selp-roster-coverage li').length).toBe(1)
  })

  it('有 active_gates.items 时渲染检查项总览', async () => {
    statusMock.mockResolvedValue({
      active_gates: {
        ok: false,
        blocking_count: 1,
        blocking_keys: ['roster'],
        items: [
          { key: 'roster', label: '排班检查', blocking: true, reason: '缺失' },
          { key: 'qa', label: 'QA', blocking: false, status: 'pass' },
        ],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-active-gates').exists()).toBe(true)
    const gates = wrapper.findAll('.selp-active-gate')
    expect(gates.length).toBe(2)
    expect(gates[0].classes()).toContain('selp-active-gate--bad')
  })

  it('无 active_gates.items 时不渲染检查项总览', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-active-gates').exists()).toBe(false)
  })

  it('有 surface_incidents 时渲染模块异常事件', async () => {
    statusMock.mockResolvedValue({
      contract_validation: {
        surface_incidents: [
          { id: 'inc-1', surface: 'employee_space', severity: 'bad', title: '断点A', action: 'fix' },
        ],
        surface_incident_summary: { total: 1, status: 'bad' },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-contract-incidents').exists()).toBe(true)
    expect(wrapper.findAll('.selp-contract-incident').length).toBe(1)
  })

  it('有 governance_audit.recent 时渲染操作审计列表', async () => {
    statusMock.mockResolvedValue({
      governance_audit: {
        summary: { health: 'ok', success_count: 5, failure_count: 0, consecutive_failures: 0 },
        recent: [
          { action: 'onboard', status: 'success', created_at: '2026-01-01', onboard_summary: { onboarded: 1, skipped: 0, failed: 0 } },
        ],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-governance-audit').exists()).toBe(true)
    expect(wrapper.findAll('.selp-governance-audit li').length).toBe(1)
  })

  it('有 open_items 时渲染待处理审批项', async () => {
    statusMock.mockResolvedValue({
      memory: {
        open_items: [
          { kind: 'approval', reason: '待审批', run_id: 'r1', created_at: '2026-01-01' },
        ],
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-open-items').exists()).toBe(true)
    expect(wrapper.findAll('.selp-open-item').length).toBe(1)
  })

  it('渲染系统状态检查 contract 区块', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      evidence: { open_run_ids: [] },
      memory: { open_items: [] },
      current_gate: { should_run: false },
      contract: {
        required_top_level: ['evidence', 'memory', 'current_gate'],
        surfaces: ['employee_space', 'duty_roster_graph'],
        gate_dependencies: ['roster', 'qa'],
      },
      contract_validation: {
        ok: true,
        surface_readiness: {
          employee_space: { ok: true },
        },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-contract').exists()).toBe(true)
    expect(wrapper.find('.selp-contract--ok').exists()).toBe(true)
    expect(wrapper.find('.selp-contract-head strong').text()).toContain('self_maintenance_runtime.v1')
  })

  it('contract 缺失必需字段时标记异常', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'self_maintenance_runtime.v1',
      contract: { required_top_level: ['evidence', 'memory'] },
      // 缺少 memory
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-contract--bad').exists()).toBe(true)
  })

  it('schema_version 不匹配时 contract 异常', async () => {
    statusMock.mockResolvedValue({
      schema_version: 'unknown.v0',
      contract: { required_top_level: ['evidence'] },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-contract--bad').exists()).toBe(true)
  })

  it('有 ui_bridge 时渲染操作引导区', async () => {
    statusMock.mockResolvedValue({
      ui_bridge: {
        state: 'governance_degraded',
        title: '需要治理',
        detail: '请处理',
        primary_employee_id: 'emp-001',
        target_employee_ids: ['emp-001'],
        next_actions: ['onboard', 'review'],
        primary_view: 'department',
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-ui-bridge').exists()).toBe(true)
    expect(wrapper.find('.selp-ui-bridge-main strong').text()).toBe('需要治理')
    // 路径与动作
    expect(wrapper.find('.selp-ui-bridge-foot').exists()).toBe(true)
  })

  it('ui_bridge 缺失时不渲染操作引导区', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.selp-ui-bridge').exists()).toBe(false)
  })

  it('有 para_task_id 时渲染复制按钮', async () => {
    statusMock.mockResolvedValue({
      memory: {
        last_run: { para_task_id: 'para-123' },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const copyBtn = wrapper.find('.selp-copy')
    expect(copyBtn.exists()).toBe(true)
    expect(copyBtn.text()).toBe('复制 ID')
  })

  it('点击复制按钮调用 clipboard 并切换文案', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    statusMock.mockResolvedValue({
      memory: { last_run: { para_task_id: 'para-456' } },
    })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.selp-copy').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('para-456')
    expect(wrapper.find('.selp-copy').text()).toBe('已复制')
  })

  it('surface=duty-roster 且满足治理复核条件时渲染复核按钮', async () => {
    statusMock.mockResolvedValue({
      ui_bridge: {
        state: 'governance_degraded',
        governance_action: {
          requires_admin: true,
          allowed_surfaces: ['duty_roster_graph'],
          id: 'inspect_governance_audit',
        },
      },
      governance_audit: {
        summary: { health: 'bad' },
      },
    })
    const wrapper = mountComponent({ surface: 'duty-roster' })
    await flushPromises()
    const btn = wrapper.find('.selp-ui-bridge-actions button')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('人工复核审计')
  })

  it('点击复核按钮调用 governanceReview API', async () => {
    reviewMock.mockResolvedValue({ summary: { health: 'ok' } })
    statusMock.mockResolvedValue({
      ui_bridge: {
        state: 'governance_degraded',
        governance_action: {
          requires_admin: true,
          allowed_surfaces: ['duty_roster_graph'],
          id: 'inspect_governance_audit',
        },
      },
      governance_audit: { summary: { health: 'bad' } },
    })
    const wrapper = mountComponent({ surface: 'duty-roster' })
    await flushPromises()
    await wrapper.find('.selp-ui-bridge-actions button').trigger('click')
    await flushPromises()
    expect(reviewMock).toHaveBeenCalledTimes(1)
    // 复核成功后展示结果
    expect(wrapper.find('.selp-ui-bridge-review--ok').exists()).toBe(true)
  })

  it('复核 API 失败时展示错误文案', async () => {
    reviewMock.mockRejectedValue(new Error('权限不足'))
    statusMock.mockResolvedValue({
      ui_bridge: {
        state: 'governance_degraded',
        governance_action: {
          requires_admin: true,
          allowed_surfaces: ['duty_roster_graph'],
          id: 'inspect_governance_audit',
        },
      },
      governance_audit: { summary: { health: 'bad' } },
    })
    const wrapper = mountComponent({ surface: 'duty-roster' })
    await flushPromises()
    await wrapper.find('.selp-ui-bridge-actions button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.selp-ui-bridge-review--bad').exists()).toBe(true)
    expect(wrapper.find('.selp-ui-bridge-review--bad').text()).toContain('权限不足')
  })

  it('surface=employee-space 时不渲染复核按钮（不满足条件）', async () => {
    statusMock.mockResolvedValue({
      ui_bridge: {
        state: 'governance_degraded',
        governance_action: {
          requires_admin: true,
          allowed_surfaces: ['duty_roster_graph'],
          id: 'inspect_governance_audit',
        },
      },
      governance_audit: { summary: { health: 'bad' } },
    })
    const wrapper = mountComponent({ surface: 'employee-space' })
    await flushPromises()
    // employee-space 不满足 canReviewGovernanceAudit
    const btn = wrapper.find('.selp-ui-bridge-actions button')
    expect(btn.exists()).toBe(false)
  })

  it('非 compact 时渲染底部策略区含自动合并与分支信息', async () => {
    statusMock.mockResolvedValue({
      policy: { auto_merge_low_risk: true, auto_merge_max_risk_score: 30, auto_merge_min_safety_score_v2: 70 },
      memory: { last_run: { branch: 'fix/bug-1', action: 'merged' } },
    })
    const wrapper = mountComponent({ compact: false })
    await flushPromises()
    const policies = wrapper.findAll('.selp-policy')
    expect(policies.length).toBe(2)
    expect(policies[0].find('strong').text()).toBe('低风险开启')
    expect(policies[1].find('strong').text()).toBe('fix/bug-1')
  })

  it('有 risk_score 时 loopStages 风险检查显示分数', async () => {
    statusMock.mockResolvedValue({
      memory: {
        last_policy_decision: {
          safety_score_v3: { score: 85, min_allowed: 60 },
        },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const stages = wrapper.findAll('.selp-stage')
    const riskStage = stages.find((s) => s.find('.selp-stage-title').text() === '风险检查')
    expect(riskStage).toBeTruthy()
    expect(riskStage!.find('.selp-stage-value').text()).toBe('85')
  })

  it('qa_verdict=PASS 时 QA 阶段为 ok tone', async () => {
    statusMock.mockResolvedValue({
      memory: {
        last_run: { qa_verdict: 'PASS' },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const stages = wrapper.findAll('.selp-stage')
    const qaStage = stages.find((s) => s.find('.selp-stage-title').text() === 'QA JSON')
    expect(qaStage).toBeTruthy()
    expect(qaStage!.find('.selp-stage-value').text()).toBe('PASS')
    expect(qaStage!.classes()).toContain('selp-stage--ok')
  })

  it('actionLabel 含 merge 时合并阶段为 ok tone', async () => {
    statusMock.mockResolvedValue({
      memory: {
        last_policy_decision: { action: 'auto_merge' },
        last_run: { branch: 'feature/x' },
      },
    })
    const wrapper = mountComponent()
    await flushPromises()
    const stages = wrapper.findAll('.selp-stage')
    const mergeStage = stages.find((s) => s.find('.selp-stage-title').text() === '合并/审批')
    expect(mergeStage).toBeTruthy()
    expect(mergeStage!.find('.selp-stage-value').text()).toBe('auto_merge')
    expect(mergeStage!.classes()).toContain('selp-stage--ok')
  })

  it('evidenceCards 渲染 Para 任务/待处理/最近运行/冷却', async () => {
    statusMock.mockResolvedValue({
      memory: {
        open_items: [{ kind: 'a' }, { kind: 'b' }],
        recent_runs: [{ id: 'r1' }, { id: 'r2' }, { id: 'r3' }],
      },
      policy: { cooldown_minutes: 120 },
    })
    const wrapper = mountComponent()
    await flushPromises()
    // 第一个 meta-card 是每日调度，后面是 evidenceCards
    const cards = wrapper.findAll('.selp-meta-card')
    expect(cards.length).toBe(5) // 1 cron + 4 evidence
    expect(cards[1].find('span').text()).toBe('Para 任务')
    expect(cards[1].find('strong').text()).toBe('无进行中任务')
    expect(cards[2].find('strong').text()).toBe('2')
    expect(cards[3].find('strong').text()).toBe('3')
    expect(cards[4].find('strong').text()).toContain('120')
  })

  it('组件卸载时清理定时器（不报错）', async () => {
    statusMock.mockResolvedValue({})
    const wrapper = mountComponent()
    await flushPromises()
    expect(() => wrapper.unmount()).not.toThrow()
  })
})
