import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { exportCandidate, githubReadEnv } from './github_para_candidate.mjs';

test('private clone authentication is temporary and scoped to the original repository', () => {
  const input = { GITHUB_ACTIONS: 'true', PARA_GITHUB_STAGE: 'resume', GITHUB_REPOSITORY: 'owner/private',
    GITHUB_TOKEN: 'read-only', GIT_CONFIG_COUNT: '9', GIT_CONFIG_KEY_8: 'malicious' };
  const env = githubReadEnv(input);
  assert.equal(env.GIT_CONFIG_COUNT, '1');
  assert.equal(env.GIT_CONFIG_KEY_0, 'http.https://github.com/owner/private.git.extraheader');
  assert.equal(env.GIT_CONFIG_KEY_8, undefined);
  assert.equal(env.GH_TOKEN, undefined);
  assert.equal(input.GIT_CONFIG_COUNT, '9');
});

test('real Git candidate is an exact commit bundle, remains unpublished and cannot overwrite another fix', async () => {
  const root = mkdtempSync(join(tmpdir(), 'para-candidate-'));
  try {
    const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore','pipe','pipe'] }).trim();
    git(['init', '-b', 'main']); git(['config', 'user.email', 'test@example.test']); git(['config', 'user.name', 'Test']);
    writeFileSync(join(root, 'app.txt'), 'before\n'); git(['add', '.']); git(['commit', '-m', 'base']);
    const base = git(['rev-parse', 'HEAD']);
    git(['checkout', '-b', 'devfleet/codex/sub-test']);
    writeFileSync(join(root, 'app.txt'), 'after\n'); git(['commit', '-am', 'candidate']);
    const request = '11111111-2222-4333-8444-555555555555';
    const marker = createHash('sha256').update(request).digest('hex').slice(0, 32);
    const task = { task_id: 'task-1', subtask_id: 'sub-1', title: `[xcmax:${marker}:${'a'.repeat(32)}] worker`,
      work_branch: 'devfleet/codex/sub-test', repo_url: 'https://github.com/owner/repo.git', auto_merge: false };
    const env = { GITHUB_ACTIONS: 'true', GITHUB_RUN_ATTEMPT: '1', GITHUB_RUN_ID: '123',
      GITHUB_SHA: base, GITHUB_REPOSITORY: 'owner/repo', PARA_GITHUB_STAGE: 'execute',
      PARA_GITHUB_REQUEST_ID: request, PARA_GITHUB_CANDIDATE_DIR: join(root, '.git', 'candidate') };
    const receipt = await exportCandidate(task, root, base, env);
    assert.equal(receipt.pushed, false); assert.equal(receipt.publication, 'artifact_pending');
    const manifest = JSON.parse(readFileSync(join(env.PARA_GITHUB_CANDIDATE_DIR, 'manifest.json')));
    assert.equal(manifest.attempt_id, 'a'.repeat(32)); assert.equal(manifest.commit_sha, git(['rev-parse', 'HEAD']));
    assert.match(git(['bundle', 'list-heads', join(env.PARA_GITHUB_CANDIDATE_DIR, 'candidate.bundle')]), /refs\/heads\/devfleet\/codex\/sub-test$/);
    await assert.rejects(exportCandidate(task, root, base, env), /EEXIST/);
    await assert.rejects(exportCandidate({ ...task, work_branch: 'main' }, root, base, env), /identity_mismatch/);
    await assert.rejects(exportCandidate(task, root, base, { ...env, GITHUB_SHA: 'f'.repeat(40) }), /identity_mismatch/);
    await assert.rejects(exportCandidate(task, root, base, { ...env, PARA_GITHUB_STAGE: 'resume' }), /identity_mismatch/);
    const repair = await exportCandidate(task, root, base, {
      ...env, GITHUB_SHA: 'f'.repeat(40), PARA_GITHUB_SOURCE_SHA: base,
      PARA_GITHUB_CANDIDATE_DIR: join(root, '.git', 'original-pr-candidate'),
    });
    assert.equal(repair.base_sha, base);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
