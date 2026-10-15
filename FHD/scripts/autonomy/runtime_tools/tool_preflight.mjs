/** Bounded, non-mutating CLI launch probes; stdout and credentials never leave the device. */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);
export async function probeTools(commands, run = execute) {
  const rows = await Promise.all(Object.entries(commands).map(async ([tool, command]) => {
    let ok = false;
    try {
      await run(command, ['--version'], { timeout: 5000, maxBuffer: 16384, windowsHide: true });
      ok = true;
    } catch { /* Evidence is false, never inferred from PATH or file existence. */ }
    return [tool, { ok, checked_at: new Date().toISOString(), kind: 'cli_launch' }];
  }));
  return Object.fromEntries(rows);
}
