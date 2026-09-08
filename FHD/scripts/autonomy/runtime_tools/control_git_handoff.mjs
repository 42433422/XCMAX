/** Platform-independent readback of a Git commit and its canonical source archive. */
import { createHash } from 'node:crypto';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';
// Run a fixed executable with argument arrays; never interpret a shell command.
const execFileAsync = promisify(execFile);
export async function sourceIdentity(directory, expectedCommit, expectedDigest = '') {
  const state = await execFileAsync('git', ['status', '--porcelain', '--untracked-files=normal'], { cwd: directory, shell: false, timeout: 10000 });
  if (state.stdout.trim()) throw new Error('handoff_workspace_not_clean');
  const { stdout } = await execFileAsync('git', ['rev-parse', 'HEAD'], { cwd: directory, shell: false, timeout: 10000 });
  const commit = stdout.trim();
  if (!/^[0-9a-f]{40}$/.test(commit) || (expectedCommit && commit !== expectedCommit)) throw new Error('handoff_commit_mismatch');
  const child = spawn('git', ['archive', '--format=tar', commit], { cwd: directory, stdio: ['ignore', 'pipe', 'ignore'] });
  const done = new Promise((resolve, reject) => {
    child.once('error', reject); child.once('close', code => code === 0 ? resolve() : reject(new Error('source_archive_failed')));
  });
  const timer = setTimeout(() => child.kill('SIGTERM'), 120000);
  try {
    const hash = createHash('sha256');
    await Promise.all([done, (async () => { for await (const chunk of child.stdout) hash.update(chunk); })()]);
    const archive_sha256 = hash.digest('hex');
    if (expectedDigest && archive_sha256 !== expectedDigest) throw new Error('handoff_archive_mismatch');
    return { source: 'executor_git_readback', commit_sha: commit, archive_sha256 };
  } finally { clearTimeout(timer); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  sourceIdentity(process.cwd(), process.argv[2], process.argv[3])
    .then(result => process.stdout.write(JSON.stringify(result) + '\n'))
    .catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
