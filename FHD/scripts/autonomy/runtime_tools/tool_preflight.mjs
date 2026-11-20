/** Bounded CLI launch probes. Reports the version and failure category. */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { modelChildEnv } from './credential_vault.mjs';

const execute = promisify(execFile);
export async function probeTools(commands, run = execute) {
  const rows = await Promise.all(Object.entries(commands).map(async ([tool, command]) => {
    let outcome = { ok: false, reason: 'not_found' };
    if (command) {
      try {
        const { stdout, stderr } = await run(command, ['--version'], { timeout: 5000, maxBuffer: 16384, windowsHide: true, env: modelChildEnv(process.env) }) || {};
        const version = String(stdout || stderr || '').match(/\b\d{1,4}\.\d{1,4}(?:\.\d{1,4})?(?:-[a-zA-Z0-9.]{1,24})?\b/)?.[0];
        outcome = { ok: true, version };
      } catch (error) {
        outcome.reason = error?.code === 'ENOENT' ? 'not_found' : error?.killed ? 'timeout' : 'launch_error';
      }
    }
    return [tool, { ...outcome, checked_at: new Date().toISOString(), kind: 'cli_launch' }];
  }));
  return Object.fromEntries(rows);
}
