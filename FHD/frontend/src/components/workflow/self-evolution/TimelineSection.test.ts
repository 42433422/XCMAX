import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import TimelineSection from './TimelineSection.vue'

it('renders running QA and review evidence with roster warnings and distinguishes failed checks', async () => {
  const wrapper = mount(TimelineSection, { props: { timeline: null,
    reviewDimStatus: (item, key) => item.review_dimensions[key] || '未检查',
    reviewDimFailed: (item, key) => item.review_dimensions[key] === 'FAIL',
  } })
  expect(wrapper.find('.selp-timeline').exists()).toBe(false)
  await wrapper.setProps({ timeline: { runId: 'run-7', open: true, items: [
    { label: '验收检查', phase: 'qa', employee_id: 'qa-1', role_label: '质量检查', status: 'done',
      roster_label: '不在排班', roster_status: 'out_of_roster', duty_registered_label: '已登记', department_label: '质量部',
      para_task_id: 'task-7', branch: 'feature/payroll', qa_verdict: 'PASS', review_max_severity: 'high', created_at: '2026-10-15',
      qa_target_branch_available: true, qa_risk_class: 'medium', qa_tested_commands: ['npm test'], qa_blocking_findings: ['账目不平'],
      review_findings: ['缺少校验'], review_blocking_findings: ['权限越界'], review_dimensions: { security: 'FAIL', business_logic: 'PASS' } },
    { step: '复测', qa_verdict: 'FAIL', qa_target_branch_available: false }, { phase: '结束' }, {},
  ] } })
  expect(wrapper.get('.selp-timeline-head').text()).toContain('#run-7 · 运行中')
  expect(wrapper.findAll('.selp-timeline-main > strong').map(node => node.text())).toEqual(['验收检查', '复测', '结束', '事件'])
  expect(wrapper.get('.selp-timeline-roster--outside').text().replace(/\s+/g, ' ')).toContain('不在排班 · 已登记 · 质量部')
  const pills = wrapper.findAll('.selp-report-pill').map(node => node.text())
  for (const text of ['QA PASS', 'QA FAIL', '分支 正常', '分支 缺失', '风险 medium', '审查 high', '测试 1', '阻断项 1', '发现 1', '审阻断 1', 'security FAIL', 'business_logic PASS', 'performance 未检查']) expect(pills).toContain(text)
  expect(wrapper.findAll('.selp-report-pill--bad').map(node => node.text())).toContain('security FAIL')
  await wrapper.setProps({ timeline: { runId: '', open: false, items: [{ department_label: '人事部' }] } })
  expect(wrapper.get('.selp-timeline-head').text()).toContain('#未知')
  expect(wrapper.get('.selp-timeline-roster').text()).toContain('排班未知')
  expect(wrapper.find('.selp-report').exists()).toBe(false)
  wrapper.unmount()
})
