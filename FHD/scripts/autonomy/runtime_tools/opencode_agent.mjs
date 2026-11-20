import { execFile } from 'node:child_process';
import { accessSync, constants, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { delimiter, join, resolve } from 'node:path';
import { promisify } from 'node:util';

const execute = promisify(execFile);

export function openCodeExecutable(env = process.env) {
  const command = env.DEVFLEET_OPENCODE_AGENT?.trim() || (process.platform === 'win32' ? 'opencode.exe' : 'opencode');
  const candidates = command.includes('/') || command.includes('\\')
    ? [resolve(command)]
    : [join(homedir(), '.opencode', 'bin', command),
      ...(env.PATH || '').split(delimiter).filter(Boolean).map(directory => resolve(directory, command))];
  return candidates.find(path => {
    try {
      accessSync(path, constants.X_OK);
      return statSync(path).isFile();
    } catch {
      return false;
    }
  });
}

function events(stdout = '') {
  return stdout.split(/\r?\n/).flatMap(line => {
    try { return [JSON.parse(line)]; } catch { return []; }
  });
}

export async function runOpenCodeAgent(cwd, prompt, { env, timeoutMs, reportOnly, executable = openCodeExecutable() }) {
  if (!executable) {
    const reason = 'OpenCode CLI is not installed';
    throw Object.assign(new Error(reason), { code: 'ENOENT', stderr: reason });
  }
  const args = ['run', '--format', 'json'];
  if (reportOnly) args.push('--agent', 'plan');
  const run = execute(executable, args, {
    cwd, timeout: timeoutMs, maxBuffer: 10 * 1024 * 1024, windowsHide: true,
    env: {
      ...env,
      OPENCODE_DISABLE_PROJECT_CONFIG: 'true',
      OPENCODE_DISABLE_AUTOUPDATE: 'true',
      ...(reportOnly ? { OPENCODE_PERMISSION: '{"edit":"deny","bash":"deny","task":"deny","external_directory":"deny"}' } : {}),
    },
  });
  run.child.stdin?.on('error', () => {}); // The process outcome carries early exits.
  run.child.stdin?.end(prompt);
  const { stdout } = await run.catch(error => {
    const event = events(error.stdout).findLast(item => item?.type === 'error');
    error.stdout = event?.error?.data?.message || '';
    throw error;
  });
  return events(stdout).filter(event => event?.type === 'text' && typeof event.part?.text === 'string')
    .map(event => event.part.text).join('\n').trim();
}
