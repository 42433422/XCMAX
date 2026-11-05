import { expect, it, vi, afterEach } from 'vitest'
import { buildDutyRosterRows } from '../../admin-console/src/utils/dutyRosterEmployeeList'

function node(tag: string, id = '', className = '', text = '') {
  const el = document.createElement(tag)
  Object.assign(el, { id, className, textContent: text })
  return el
}
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllTimers(); vi.useRealTimers() })
it('does not infer all planned employees installed from one aggregate installation', () => {
  const rows = buildDutyRosterRows({ planned_employee_ids: ['test-a', 'test-b'],
    registered_employee_ids: ['test-a', 'test-b'], local_employee_pack_ids: ['test-a'], planned_local_installed_count: 1 })
  expect(rows.find(r => r.pkgId === 'test-a')?.status).toBe('installed')
  expect(rows.find(r => r.pkgId === 'test-b')?.status).toBe('registered')
  expect(buildDutyRosterRows({ planned_employee_ids: ['test-a'], planned_local_installed_count: 1 })
    .find(r => r.pkgId === 'test-a')?.status).toBe('planned')
})
it('updates acquisition steps without writing the partner line percentage', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, headers: new Headers(),
    json: async () => String(url).includes('operations') ? { steps: { O1: { status: 'done' } } } : null })))
  const step = node('div', '', 'ops-step-node')
  step.dataset.opsStep = 'O1'
  step.append(node('i', '', 'node-dot'), node('b', '', 'node-tag'))
  const refresh = node('button', 'btn-refresh-health')
  document.body.append(node('div', 'ops-loop-progress-num', '', '75%'), step, refresh)
  await import('../../../docs/xcagi-dashboard/app.js')
  document.dispatchEvent(new Event('DOMContentLoaded'))
  refresh.click()
  await vi.waitFor(() => expect(document.querySelector('.node-dot')?.classList.contains('done')).toBe(true))
  expect(document.querySelector('.node-dot')?.classList.contains('done')).toBe(true)
  expect(document.getElementById('ops-loop-progress-num')?.textContent).toBe('75%')
})
it('shows an unknown roster when no report loaded, preserving reported zero', async () => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  let report: object | null = null
  vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, headers: new Headers(),
    json: async () => String(url).includes('xcmax-step-employee-coverage') ? report : null })))
  document.body.append(node('div', 's-workflow', 'section'), node('div', 'emp-wf-roster'), node('div', 'emp-wf-tagline'))
  await import('../../../docs/xcagi-dashboard/app.js')
  const go = (window as unknown as { go: (tab: string) => void }).go
  go('workflow')
  await vi.waitFor(() => expect(document.getElementById('emp-wf-roster')?.textContent).toBe('—'))
  report = { roster_count: 0, roster_in_steps_count: 0 }
  go('workflow')
  await vi.waitFor(() => expect(document.getElementById('emp-wf-roster')?.textContent).toBe('0'))
})
