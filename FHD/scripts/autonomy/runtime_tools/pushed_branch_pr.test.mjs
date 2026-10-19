import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import {
  buildPushedPrRequest, describePushedPrFailure, ensurePullRequestForPushedBranch,
  parseGithubRepoFull, pushedPrBaseBranch, requirePrUrlAfterPush, shouldOpenPrForPushedTask,
} from './pushed_branch_pr.mjs';

const task = {
  task_id: 'f71572cc', subtask_id: '09d6d188', work_branch: 'devfleet/codex/sub-1-adc0ac',
  base_branch: 'main', repo_url: 'https://github.com/42433422/XCMAX.git', auto_merge: false,
  title: '工单 40 提交人身份', description: '客户原文不应进入 PR 正文',
};

test('auto_merge=0 的 GitHub 代码任务 push 后必须开 PR；auto_merge=true 交给 merge-worker', () => {
  assert.deepEqual(shouldOpenPrForPushedTask(task, {}), { open: true, reason: '' });
  assert.equal(shouldOpenPrForPushedTask({ ...task, auto_merge: true }, {}).open, false);
  assert.equal(shouldOpenPrForPushedTask(task, { DEVFLEET_OPEN_PR_ON_PUSH: '0' }).reason, 'disabled_by_env');
  assert.equal(shouldOpenPrForPushedTask({ ...task, repo_url: '/tmp/bare.git' }, {}).reason, 'not_github_repo');
  assert.equal(parseGithubRepoFull('git@github.com:42433422/XCMAX.git'), '42433422/XCMAX');
  assert.equal(pushedPrBaseBranch({ base_branch: 'a'.repeat(40) }), 'main');
});

test('PR 带 hold-merge、不开 auto-merge，标题正文不含任务标题与描述', async () => {
  const calls = [];
  const result = await ensurePullRequestForPushedBranch(buildPushedPrRequest(task), async (args) => {
    calls.push(args);
    return args[1] === 'list' ? '[]' : 'https://github.com/42433422/XCMAX/pull/2411\n';
  });
  assert.deepEqual(result, { url: 'https://github.com/42433422/XCMAX/pull/2411', number: '2411', created: true });
  const create = calls[1];
  assert.equal(create[create.indexOf('--label') + 1], 'hold-merge'); assert.equal(create.includes('--auto'), false);
  assert.equal(create[create.indexOf('--body') + 1].includes('客户原文'), false);
  assert.equal(create[create.indexOf('--title') + 1], 'devfleet: Para 任务 f71572cc 产物（devfleet/codex/sub-1-adc0ac）');
});

test('已有 open PR 时复用，不重复创建；gh 认证失败给出明确原因', async () => {
  const result = await ensurePullRequestForPushedBranch(buildPushedPrRequest(task), async (args) => {
    assert.equal(args[1], 'list');
    return '[{"number":2410,"url":"https://github.com/42433422/XCMAX/pull/2410"}]';
  });
  assert.equal(result.created, false);
  assert.match(describePushedPrFailure(new Error('HTTP 401: Bad credentials')), /GitHub 认证失败/);
});

test('系统侧硬门：该开 PR 却没有 URL 必须 fail-closed', () => {
  assert.equal(requirePrUrlAfterPush(task, '').ok, false);
  assert.match(requirePrUrlAfterPush(task, '').reason, /pushed_without_pr/);
  assert.equal(requirePrUrlAfterPush(task, 'https://github.com/42433422/XCMAX/pull/1').ok, true);
  assert.equal(requirePrUrlAfterPush({ ...task, auto_merge: true }, '').ok, true);
});


test('PR 创建失败时，受管回执和 WebSocket 都只能报告 failed；成功后才可完成', async () => {
  const source = readFileSync(new URL('./para_e2e_agent.mjs', import.meta.url), 'utf8');
  const section = (start, end) => source.slice(source.indexOf(`async function ${start}(`), source.indexOf(`async function ${end}(`));
  for (const prUrl of ['', 'https://github.com/42433422/XCMAX/pull/1']) {
    const reports = [], messages = [];
    const context = vm.createContext({ requirePrUrlAfterPush, console,
      openPullRequestAfterPush: async () => prUrl, paraReports: { handles: () => true },
      sourceIdentity: async () => ({ head_sha: 'a'.repeat(40) }),
      postTaskReport: async (_, report) => reports.push(report),
      send: (_, message) => messages.push(message), requestMergeOnComplete: async () => {},
    });
    vm.runInContext(section('settleAfterPush', 'openPullRequestAfterPush')
      + section('reportCodeIdentity', 'handleTask'), context);
    assert.equal(await context.settleAfterPush(null, task, '/task', 'base', true, 'pushed'), Boolean(prUrl));
    const expected = prUrl ? 'completed' : 'failed';
    assert.deepEqual(reports.map(report => report.status), [expected]);
    assert.deepEqual(messages.filter(message => message.type === 'task_progress').map(message => message.status), [expected]);
  }
});
