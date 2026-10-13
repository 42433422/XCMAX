import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, it } from 'vitest'
import { buildDutyRosterRows } from '../../admin-console/src/utils/dutyRosterEmployeeList'

const source = readFileSync(resolve('../../docs/xcagi-dashboard/app.js'), 'utf8')
it('does not infer all planned employees installed from one aggregate installation', () => {
  const rows = buildDutyRosterRows({ planned_employee_ids: ['test-a', 'test-b'],
    registered_employee_ids: ['test-a', 'test-b'], local_employee_pack_ids: ['test-a'], planned_local_installed_count: 1 })
  expect(rows.find(r => r.pkgId === 'test-a')?.status).toBe('installed')
  expect(rows.find(r => r.pkgId === 'test-b')?.status).toBe('registered')
  expect(buildDutyRosterRows({ planned_employee_ids: ['test-a'], planned_local_installed_count: 1 })
    .find(r => r.pkgId === 'test-a')?.status).toBe('planned')
})
it('updates acquisition steps without writing the partner line percentage', () => {
  document.body.innerHTML = '<div id="ops-loop-progress-num">75%</div><div class="ops-step-node" data-ops-step="O1"><i class="node-dot"></i><b class="node-tag"></b></div>'
  const body = source.slice(source.indexOf('  function applyStepStatus'), source.indexOf('  function buildHealthUrls'))
  new Function('document', 'Utils', 'TAG_LABEL', body + ';applyStepStatus({O1:{status:"done"}})')(document, { safeText: (el: Element, s: string) => { el.textContent = s } }, { done: '已做' })
  expect(document.querySelector('.node-dot')?.classList.contains('done')).toBe(true)
  expect(document.getElementById('ops-loop-progress-num')?.textContent).toBe('75%')
})
it('shows an unknown roster when no report loaded, preserving reported zero', () => {
  document.body.innerHTML = '<div id="emp-wf-roster"></div><div id="emp-wf-tagline"></div>'
  const body = source.slice(source.lastIndexOf('  function renderHero'), source.indexOf('  async function activate()', source.lastIndexOf('  function renderHero')))
  const render = new Function('document', body + ';return renderHero')(document)
  render(null, null)
  expect(document.getElementById('emp-wf-roster')?.textContent).toBe('—')
  render({ roster_count: 0, roster_in_steps_count: 0 }, null)
  expect(document.getElementById('emp-wf-roster')?.textContent).toBe('0')
})
