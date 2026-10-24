import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import {
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFile);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const sources = [
  path.join(scriptDir, 'e2e-agent.mjs'),
  path.join(scriptDir, 'para_e2e_agent.mjs'),
];

async function git(cwd, args) {
  const { stdout, stderr } = await execFileAsync('git', args, {
    cwd,
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
  return (stdout || stderr).trim();
}

function loadBaseRefresh(sourcePath) {
  const source = readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('async function refreshBaseBranchFromOrigin');
  const end = source.indexOf('\nasync function cloneSourceWorkspace', start);
  assert.ok(start >= 0 && end > start, `base refresh helper not found in ${sourcePath}`);
  return Function(
    'git',
    `${source.slice(start, end)}\nreturn refreshBaseBranchFromOrigin;`,
  )(git);
}

async function commitFile(repo, name, content, message) {
  writeFileSync(path.join(repo, name), content, 'utf8');
  await git(repo, ['add', name]);
  await git(repo, ['commit', '-m', message]);
  return git(repo, ['rev-parse', 'HEAD']);
}

for (const sourcePath of sources) {
  test(`${path.basename(sourcePath)} preserves storage failures without retrying a network clone`, async () => {
    const source = readFileSync(sourcePath, 'utf8');
    const start = source.indexOf('async function cloneSourceWorkspace');
    const end = source.indexOf('\nfunction excludeAgentMetadata', start);
    assert.ok(start >= 0 && end > start);
    for (const detail of [
      { code: 'ENOSPC' },
      { code: 'EDQUOT' },
      { code: 128, stderr: 'fatal: write error: No space left on device' },
      { message: 'fatal: Disk quota exceeded' },
      { stderr: 'fatal: repository not found' },
    ]) {
      const error = Object.assign(new Error('local clone failed'), detail);
      const calls = [];
      let cleaned = false;
      const clone = Function('git', 'gitMaybe', 'removeOwnWorkspace', 'console',
        `${source.slice(start, end)}\nreturn cloneSourceWorkspace;`)(
        async (_cwd, args) => {
          calls.push(args);
          if (calls.length === 1) throw error;
        },
        async () => {},
        () => { cleaned = true; return true; },
        { error() {} },
      );
      const pending = clone('/source', '/root/task', { repo_url: 'https://example.invalid/repo', work_branch: 'fix' }, '/root');
      if (detail.stderr === 'fatal: repository not found') {
        await pending;
        assert.equal(calls.length, 2);
        assert.ok(calls[1].includes('--depth'));
        assert.equal(cleaned, true);
      } else {
        await assert.rejects(pending, (actual) => actual === error);
        assert.equal(calls.length, 1);
        assert.equal(cleaned, false);
      }
    }
  });

  test(`${path.basename(sourcePath)} starts a worktree from the current remote base`, async () => {
    const root = mkdtempSync(path.join(tmpdir(), 'xcmax-base-refresh-'));
    const remote = path.join(root, 'remote.git');
    const source = path.join(root, 'source');
    const updater = path.join(root, 'updater');
    const taskDir = path.join(root, 'task');
    try {
      await git(root, ['init', '--bare', remote]);
      await git(root, ['init', '-b', 'main', source]);
      await git(source, ['config', 'user.name', 'test']);
      await git(source, ['config', 'user.email', 'test@example.invalid']);
      await commitFile(source, 'base.txt', 'old\n', 'old base');
      await git(source, ['remote', 'add', 'origin', remote]);
      await git(source, ['push', '-u', 'origin', 'main']);

      await git(root, ['clone', remote, updater]);
      await git(updater, ['config', 'user.name', 'test']);
      await git(updater, ['config', 'user.email', 'test@example.invalid']);
      const expectedHead = await commitFile(updater, 'base.txt', 'current\n', 'current base');
      await git(updater, ['push', 'origin', 'main']);

      await git(root, ['clone', '--shared', source, taskDir]);
      await git(taskDir, ['pack-refs', '--all', '--prune']);
      assert.notEqual(await git(taskDir, ['rev-parse', 'HEAD']), expectedHead);

      const refresh = loadBaseRefresh(sourcePath);
      assert.equal(await refresh(taskDir, remote, 'main'), expectedHead);
      assert.equal(await git(taskDir, ['rev-parse', 'HEAD']), expectedHead);
      assert.equal(await git(taskDir, ['branch', '--show-current']), 'main');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
