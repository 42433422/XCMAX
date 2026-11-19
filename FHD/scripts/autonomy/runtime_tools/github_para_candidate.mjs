/** Git bundle handoff only. Publication belongs to a different GitHub-hosted job. */
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { sourceIdentity } from './control_git_handoff.mjs';

const execFileAsync = promisify(execFile);
export const CANDIDATE_SCHEMA = 'para-github-candidate/v1';
export function candidateMode(env = process.env) {
  return env.GITHUB_ACTIONS === 'true' && env.PARA_GITHUB_STAGE === 'execute';
}

export function githubReadEnv(env = process.env) {
  if (env.GITHUB_ACTIONS !== 'true' || !['execute', 'resume'].includes(env.PARA_GITHUB_STAGE)
      || !env.GITHUB_TOKEN || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPOSITORY || '')) return env;
  // The workflow grants this native job token contents:read only. Scope the temporary
  // header to this repository; never persist credentials in a candidate's .git/config.
  const clean = Object.fromEntries(Object.entries(env).filter(([key]) => !key.startsWith('GIT_CONFIG_')));
  return { ...clean, GIT_CONFIG_COUNT: '1',
    GIT_CONFIG_KEY_0: `http.https://github.com/${env.GITHUB_REPOSITORY}.git.extraheader`,
    GIT_CONFIG_VALUE_0: `AUTHORIZATION: basic ${Buffer.from(`x-access-token:${env.GITHUB_TOKEN}`).toString('base64')}` };
}

export async function exportCandidate(task, taskDir, baseHead, env = process.env) {
  const request = env.PARA_GITHUB_REQUEST_ID || '';
  const marker = createHash('sha256').update(request).digest('hex').slice(0, 32);
  const match = String(task.title || '').match(/^\[xcmax:([0-9a-f]{32}):([0-9a-f]{32})\]/);
  if (!candidateMode(env) || env.GITHUB_RUN_ATTEMPT !== '1'
      || !/^[0-9a-f-]{36}$/.test(request) || !/^\d+$/.test(env.GITHUB_RUN_ID || '')
      || !match || match[1] !== marker || task.auto_merge === true
      || !/^devfleet\/[A-Za-z0-9_./-]+$/.test(task.work_branch || '')
      || task.work_branch.includes('..') || task.work_branch.endsWith('.lock')
      || baseHead !== env.GITHUB_SHA || !/^[0-9a-f]{40}$/.test(baseHead)
      || task.repo_url !== `https://github.com/${env.GITHUB_REPOSITORY}.git`
      || !env.PARA_GITHUB_CANDIDATE_DIR) throw new Error('candidate_dispatch_identity_mismatch');
  const identity = await sourceIdentity(taskDir);
  if (identity.commit_sha === baseHead) throw new Error('candidate_has_no_commit');
  await execFileAsync('git', ['merge-base', '--is-ancestor', baseHead, identity.commit_sha], { cwd: taskDir });
  const directory = env.PARA_GITHUB_CANDIDATE_DIR;
  mkdirSync(directory, { recursive: true });
  // An immutable handoff has exactly one fix/subtask. Never select one from a set.
  writeFileSync(join(directory, '.claim'), `${task.task_id}:${task.subtask_id}`, { flag: 'wx' });
  const bundle = join(directory, 'candidate.bundle');
  await execFileAsync('git', ['bundle', 'create', bundle, `${baseHead}..${task.work_branch}`], { cwd: taskDir });
  const bytes = readFileSync(bundle);
  if (bytes.length > 64 * 1024 * 1024) throw new Error('candidate_bundle_too_large');
  const receipt = { ...identity, pushed: false, publication: 'artifact_pending', base_sha: baseHead,
    branch: task.work_branch, task_id: task.task_id, subtask_id: task.subtask_id,
    attempt_id: match[2], bundle_sha256: createHash('sha256').update(bytes).digest('hex') };
  if (JSON.stringify(receipt).length > 1000) throw new Error('candidate_receipt_too_large');
  const manifest = { schema: CANDIDATE_SCHEMA, request_id: request, run_id: env.GITHUB_RUN_ID,
    repository: env.GITHUB_REPOSITORY, ...receipt };
  writeFileSync(join(directory, 'manifest.json'), JSON.stringify(manifest) + '\n', { flag: 'wx' });
  return receipt;
}
