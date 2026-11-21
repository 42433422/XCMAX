import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { lstat, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { promisify } from 'node:util';

const execute = promisify(execFile);

export const reportOnlyPatchInstruction =
  'Read .devfleet/REPORT_ONLY_DIFF.patch for the target changes. The task workspace stays on its original branch.';

export async function writeReportOnlyPatch(cwd, evidence, timeout) {
  const refs = [evidence.base_sha, evidence.target_sha];
  if (refs.some(sha => !/^[0-9a-f]{40}(?:[0-9a-f]{24})?$/.test(sha))) {
    throw new Error('Invalid verified report-only commit SHA');
  }
  const options = { cwd, timeout, maxBuffer: 1024 * 1024 };
  const args = ['--no-pager', 'diff', '--no-ext-diff', '--no-textconv'];
  let patch;
  try {
    ({ stdout: patch } = await execute('git', [...args, ...refs, '--'], options));
  } catch (error) {
    if (error.code !== 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER') throw error;
    const { stdout: stat } = await execute('git', [...args, '--stat', ...refs, '--'], options);
    patch = `[Patch truncated at 1 MiB. Use the file summary; do not claim full review.]\n${stat}\n${error.stdout}`;
  }
  await writeTaskMetadata(cwd, 'REPORT_ONLY_DIFF.patch', patch || '[No differences between the verified commits.]\n');
}

export async function writeTaskMetadata(cwd, filename, content) {
  const metadata = join(cwd, '.devfleet');
  if (!(await lstat(metadata)).isDirectory()) throw new Error('Invalid Para task metadata directory');
  const temporary = join(metadata, randomUUID() + '.tmp');
  try {
    await writeFile(temporary, content, { flag: 'wx', mode: 0o600 });
    await rename(temporary, join(metadata, filename));
  } finally {
    await rm(temporary, { force: true });
  }
}
