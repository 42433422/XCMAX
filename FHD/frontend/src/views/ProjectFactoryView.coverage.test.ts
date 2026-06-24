import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ProjectFactoryView from './ProjectFactoryView.vue';

const { mockWorkspaces, mockEmployees, mockDispatch, mockClaudeMsgs, mockCodexMsgs } = vi.hoisted(
  () => ({
    mockWorkspaces: vi.fn(),
    mockEmployees: vi.fn(),
    mockDispatch: vi.fn(),
    mockClaudeMsgs: vi.fn(),
    mockCodexMsgs: vi.fn(),
  }),
);

vi.mock('@/api/factoryConsole', () => ({
  fetchFactoryWorkspaces: mockWorkspaces,
  fetchFactoryEmployees: mockEmployees,
  dispatchFactoryTask: mockDispatch,
}));
vi.mock('@/api/claudeSuperEmployee', () => ({ fetchClaudeSuperEmployeeMessages: mockClaudeMsgs }));
vi.mock('@/api/codexSuperEmployee', () => ({ fetchCodexSuperEmployeeMessages: mockCodexMsgs }));

const WS = [
  { id: 'xcmax', label: 'XCMAX 主项目', isolation: 'none', default_branch: 'main', vcs_kind: 'git' },
];
const EMP = [
  {
    id: 'claude-factory-employee',
    display_name: '工厂员工-Claude',
    display_tool: 'Claude',
    avatar_letter: '厂',
    summary: 's',
    scope: 'factory',
    endpoint: '/api/admin/claude-super-employee/messages',
  },
  {
    id: 'codex-factory-employee',
    display_name: '工厂员工-Codex',
    display_tool: 'Codex',
    avatar_letter: '厂',
    summary: 's',
    scope: 'factory',
    endpoint: '/api/admin/codex-super-employee/messages',
  },
];

beforeEach(() => {
  mockWorkspaces.mockReset().mockResolvedValue(WS);
  mockEmployees.mockReset().mockResolvedValue(EMP);
  mockDispatch.mockReset().mockResolvedValue({ success: true });
  mockClaudeMsgs.mockReset().mockResolvedValue([
    { id: 'm1', role: 'user', body: '改登录', created_at: '2026-06-24', task_status: 'queued' },
    { id: 'm2', role: 'assistant', body: '好的', created_at: '2026-06-24' },
    { id: 'm3', role: 'system', body: '已派工', created_at: '2026-06-24' },
  ]);
  mockCodexMsgs.mockReset().mockResolvedValue([]);
});

describe('ProjectFactoryView', () => {
  it('loads workspaces/employees/messages on mount and renders all roles', async () => {
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    expect(mockWorkspaces).toHaveBeenCalled();
    expect(mockEmployees).toHaveBeenCalled();
    expect(mockClaudeMsgs).toHaveBeenCalled(); // 默认员工 = Claude
    const text = wrapper.text();
    expect(text).toContain('项目工厂');
    expect(text).toContain('改登录');
    expect(text).toContain('我'); // roleLabel user
    expect(text).toContain('员工'); // roleLabel assistant
    expect(text).toContain('系统'); // roleLabel system
  });

  it('dispatches the typed task with the selected workspace and reloads', async () => {
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    await wrapper.find('textarea').setValue('修复登录 bug');
    mockClaudeMsgs.mockClear();
    await wrapper.find('button.btn-primary').trigger('click');
    await flushPromises();

    expect(mockDispatch).toHaveBeenCalledWith(
      '/api/admin/claude-super-employee/messages',
      '修复登录 bug',
      'xcmax',
    );
    expect(mockClaudeMsgs).toHaveBeenCalled(); // 派工后刷新记录
  });

  it('does not dispatch when the draft is empty', async () => {
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    await wrapper.find('button.btn-primary').trigger('click');
    expect(mockDispatch).not.toHaveBeenCalled();
  });

  it('switches to the Codex employee and loads codex history', async () => {
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    const employeeSelect = wrapper.findAll('select')[1];
    await employeeSelect.setValue('codex-factory-employee');
    await flushPromises();

    expect(mockCodexMsgs).toHaveBeenCalled();
  });

  it('surfaces a load error', async () => {
    mockWorkspaces.mockRejectedValueOnce(new Error('网络炸了'));
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    expect(wrapper.text()).toContain('网络炸了');
  });

  it('surfaces a non-Error load failure via String fallback', async () => {
    mockEmployees.mockRejectedValueOnce('plain-string-error');
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    expect(wrapper.text()).toContain('plain-string-error');
  });

  it('shows the empty state when there are no records', async () => {
    mockClaudeMsgs.mockResolvedValue([]);
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    expect(wrapper.text()).toContain('还没有派工记录');
  });

  it('reports a dispatch failure', async () => {
    mockDispatch.mockRejectedValueOnce(new Error('派工失败了'));
    const wrapper = mount(ProjectFactoryView);
    await flushPromises();

    await wrapper.find('textarea').setValue('做点事');
    await wrapper.find('button.btn-primary').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('派工失败了');
  });
});
