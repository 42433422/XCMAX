import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DiagnosticTerminalView from '../../../admin-console/src/views/DiagnosticTerminalView.vue'

const executeDiagnosticTerminalCommand = vi.fn()

vi.mock('../../../admin-console/src/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    executeDiagnosticTerminalCommand: (...args: unknown[]) => executeDiagnosticTerminalCommand(...args),
  },
}))

const result = (command: string, status = 'healthy') => ({
  ok: true,
  read_only: true,
  command: command.split(' ')[0],
  query: command.split(' ').slice(1).join(' '),
  status,
  summary: command === 'doctor' ? '运行面已完成快速体检' : `已执行 ${command}`,
  metrics: { database: 'ok', scheduler_failing: status === 'degraded' ? 1 : 0 },
  items: [
    {
      kind: 'scheduler',
      severity: status === 'degraded' ? 'error' : 'info',
      title: 'daily_digest',
      detail: 'success',
      source: 'scheduler_runtime',
      reference: 'job:daily_digest',
    },
  ],
  hints: ['诊断终端始终只读。'],
  generated_at: '2026-08-31T08:00:00Z',
  elapsed_ms: 12.4,
})

describe('DiagnosticTerminalView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    executeDiagnosticTerminalCommand.mockImplementation(async (command: string) => result(command))
  })

  it('opens with a real doctor command and renders structured evidence', async () => {
    const wrapper = mount(DiagnosticTerminalView)
    await flushPromises()

    expect(executeDiagnosticTerminalCommand).toHaveBeenCalledWith('doctor')
    expect(wrapper.text()).toContain('XC 诊断终端')
    expect(wrapper.text()).toContain('运行面已完成快速体检')
    expect(wrapper.text()).toContain('scheduler_failing')
    expect(wrapper.text()).toContain('daily_digest')
    expect(wrapper.text()).toContain('只读')
  })

  it('runs quick and typed commands without exposing a shell', async () => {
    executeDiagnosticTerminalCommand.mockImplementation(async (command: string) =>
      result(command, command === 'problems' ? 'degraded' : 'healthy'),
    )
    const wrapper = mount(DiagnosticTerminalView)
    await flushPromises()

    const problems = wrapper.findAll('.quick-commands button').find((button) => button.text().includes('当前问题'))
    await problems!.trigger('click')
    await flushPromises()
    expect(executeDiagnosticTerminalCommand).toHaveBeenCalledWith('problems')
    expect(wrapper.text()).toContain('异常')

    const input = wrapper.get('#diagnostic-command')
    await input.setValue('find 登录')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(executeDiagnosticTerminalCommand).toHaveBeenCalledWith('find 登录')
    expect(wrapper.text()).toContain('已执行 find 登录')
  })

  it('supports command history and local clear without another API request', async () => {
    const wrapper = mount(DiagnosticTerminalView)
    await flushPromises()
    const input = wrapper.get('#diagnostic-command')
    await input.setValue('account SUNBIRD')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await input.trigger('keydown', { key: 'ArrowUp' })
    expect((input.element as HTMLInputElement).value).toBe('account SUNBIRD')
    const before = executeDiagnosticTerminalCommand.mock.calls.length
    await wrapper.find('button.clear').trigger('click')
    expect(wrapper.findAll('.terminal-entry')).toHaveLength(0)
    expect(executeDiagnosticTerminalCommand).toHaveBeenCalledTimes(before)
  })
})
