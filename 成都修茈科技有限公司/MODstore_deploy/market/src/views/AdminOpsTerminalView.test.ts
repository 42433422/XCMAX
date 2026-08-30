import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../stores/auth'
import AdminOpsTerminalView from './AdminOpsTerminalView.vue'

const executeDiagnosticCommand = vi.fn()

vi.mock('../application/diagnosticTerminalApi', () => ({
  executeDiagnosticCommand: (...args: unknown[]) => executeDiagnosticCommand(...args),
}))

function result(command: string, status = 'healthy') {
  return {
    ok: true,
    read_only: true,
    command: command.split(' ')[0],
    query: '',
    status,
    summary: command === 'doctor' ? '运行面已完成快速体检' : `已执行 ${command}`,
    metrics: { database: 'ok', git_sha: 'abc123' },
    items: [
      {
        kind: 'scheduler',
        severity: status === 'degraded' ? 'error' : 'info',
        title: 'daily_digest',
        detail: status === 'degraded' ? 'digest_timeout' : 'success',
        source: 'scheduler_runtime',
        reference: 'job:daily_digest',
      },
    ],
    hints: ['输入 find <关键词> 跨域搜索。'],
    generated_at: '2026-08-31T00:00:00Z',
    elapsed_ms: 12.5,
  }
}

describe('AdminOpsTerminalView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.user = {
      id: 1,
      username: 'admin',
      email: 'admin@example.com',
      is_admin: true,
    }
    executeDiagnosticCommand.mockReset()
    executeDiagnosticCommand.mockImplementation(async (command: string) => result(command))
  })

  it('runs a real doctor command on entry and renders structured evidence', async () => {
    const wrapper = mount(AdminOpsTerminalView)
    await flushPromises()

    expect(executeDiagnosticCommand).toHaveBeenCalledWith('doctor')
    expect(wrapper.text()).toContain('XC 诊断终端')
    expect(wrapper.text()).toContain('只读')
    expect(wrapper.text()).toContain('运行面已完成快速体检')
    expect(wrapper.text()).toContain('database')
    expect(wrapper.text()).toContain('daily_digest')
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('a').attributes('target')).toBe('_blank')
  })

  it('executes quick commands and clearly renders a degraded result', async () => {
    executeDiagnosticCommand.mockImplementation(async (command: string) => result(command, command === 'problems' ? 'degraded' : 'healthy'))
    const wrapper = mount(AdminOpsTerminalView)
    await flushPromises()

    const problems = wrapper.findAll('.quick-command-bar button').find((button) => button.text().includes('当前问题'))
    expect(problems).toBeDefined()
    await problems!.trigger('click')
    await flushPromises()

    expect(executeDiagnosticCommand).toHaveBeenLastCalledWith('problems')
    expect(wrapper.text()).toContain('异常')
    expect(wrapper.text()).toContain('digest_timeout')
    expect(wrapper.find('.status-degraded').exists()).toBe(true)
  })

  it('supports typed commands, history and clear without executing shell', async () => {
    const wrapper = mount(AdminOpsTerminalView)
    await flushPromises()
    const input = wrapper.find<HTMLInputElement>('#xcmax-terminal-command')
    await input.setValue('account terminal_customer')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(executeDiagnosticCommand).toHaveBeenLastCalledWith('account terminal_customer')
    await input.trigger('keydown', { key: 'ArrowUp' })
    expect(input.element.value).toBe('account terminal_customer')

    const clear = wrapper.findAll('.terminal-command-form button').find((button) => button.text() === '清屏')
    await clear!.trigger('click')
    expect(wrapper.findAll('.terminal-entry')).toHaveLength(0)
  })
})
