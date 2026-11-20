import { execFile, spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { accessSync, constants, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { delimiter, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { Readable } from 'node:stream';
import { promisify } from 'node:util';
import { streamCliOutput } from './cli_output_stream.mjs';

const execute = promisify(execFile);

export function openCodePlatformConfig(env) {
  const gateway = new URL(env.PARA_PLATFORM_GATEWAY_URL || '');
  const model = env.PARA_OPENCODE_MODEL?.trim();
  if (gateway.protocol !== 'https:' || gateway.username || gateway.password || gateway.search || gateway.hash
      || !model || !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(model) || !env.OPENCODE_API_KEY?.trim()) {
    throw new Error('OpenCode 缺少有效的 XCMAX 网关地址、模型别名或专用密钥');
  }
  return {
    model: 'xcmax/' + model,
    small_model: 'xcmax/' + model,
    enabled_providers: ['xcmax'],
    provider: { xcmax: { npm: '@ai-sdk/openai', name: 'XCMAX',
      options: { baseURL: gateway.href.replace(/\/$/, ''), apiKey: '{env:OPENCODE_API_KEY}' },
      models: { [model]: { name: model } } } },
  };
}

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

async function runOpenCodeLive(executable, cwd, prompt, env, options) {
  const password = randomUUID();
  const signal = AbortSignal.timeout(options.timeoutMs);
  const server = spawn(executable, ['serve', '--hostname', '127.0.0.1', '--port', '0'], {
    cwd, env: { ...env, OPENCODE_SERVER_PASSWORD: password }, stdio: ['ignore', 'pipe', 'ignore'],
  });
  const headers = { authorization: 'Basic ' + Buffer.from('opencode:' + password).toString('base64') };
  let stream;
  let deadline;
  let pending = '';
  const flush = () => {
    clearTimeout(deadline);
    deadline = undefined;
    if (pending) options.log('[OpenCode] ' + pending);
    pending = '';
  };
  try {
    const base = await new Promise((resolve, reject) => {
      const output = createInterface({ input: server.stdout });
      server.once('error', reject);
      server.once('close', code => reject(new Error('OpenCode 服务启动失败，退出码 ' + code)));
      signal.addEventListener('abort', () => reject(new Error('OpenCode 服务启动超时')), { once: true });
      output.on('line', line => {
        const url = line.match(/http:\/\/127\.0\.0\.1:[1-9][0-9]*/)?.[0];
        if (url) resolve(url);
      });
    });
    const request = async (route, body) => {
      const result = await fetch(base + route, {
        signal, headers: { ...headers, 'content-type': 'application/json' },
        ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}),
      });
      if (!result.ok) throw new Error('OpenCode HTTP ' + result.status + ' ' + (await result.text()).slice(0, 700));
      return result;
    };
    const session = await (await request('/session', { title: 'Para task' })).json();
    const textParts = new Set();
    stream = Readable.fromWeb((await request('/event')).body);
    stream.on('error', () => {}); // Request/timeout reports the final status.
    const lines = createInterface({ input: stream });
    lines.on('line', line => {
      if (!line.startsWith('data:')) return;
      const event = events(line.slice(5).trim())[0];
      const fields = event?.properties;
      if (!fields || (fields.sessionID || fields.part?.sessionID) !== session.id) return;
      if (event.type === 'message.part.updated' && fields.part?.type === 'text') {
        textParts.add(fields.part.id);
      }
      if (event.type === 'message.part.updated' && fields.part?.type === 'tool' && fields.part.state?.status === 'running') {
        flush();
        options.log('[OpenCode] 正在调用工具');
      }
      if (event.type === 'message.part.delta' && fields.field === 'text' && textParts.has(fields.partID) && typeof fields.delta === 'string') {
        pending += fields.delta;
        if (pending.length >= 1000) flush();
        else deadline ??= setTimeout(flush, 150);
      }
    });
    options.log('[OpenCode] 会话已启动');
    const response = await (await request('/session/' + encodeURIComponent(session.id) + '/message', {
      parts: [{ type: 'text', text: prompt }],
      ...(options.reportOnly ? { agent: 'plan' } : {}),
      ...(options.platform ? { model: { providerID: 'xcmax', modelID: env.PARA_OPENCODE_MODEL.trim() } } : {}),
    })).json();
    flush();
    const error = response.info?.error;
    if (error) throw new Error(error.data?.message || error.name || 'OpenCode 模型请求失败');
    const tokens = response.info?.tokens;
    if (Number.isFinite(tokens?.input) && Number.isFinite(tokens?.output)) {
      options.log('[OpenCode] 模型用量：输入 ' + tokens.input + '，输出 ' + tokens.output + ' token');
    }
    return (response.parts || []).filter(part => part.type === 'text').map(part => part.text).join('\n').trim();
  } catch (error) {
    throw Object.assign(error, { stderr: error.message });
  } finally {
    flush();
    stream?.destroy();
    server.kill('SIGTERM');
    const stop = setTimeout(() => {
      if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL');
    }, 2000);
    stop.unref();
    server.once('close', () => clearTimeout(stop));
  }
}

export async function runOpenCodeAgent(cwd, prompt, { env, timeoutMs, reportOnly, log, executable = openCodeExecutable() }) {
  if (!executable) {
    const reason = 'OpenCode CLI is not installed';
    throw Object.assign(new Error(reason), { code: 'ENOENT', stderr: reason });
  }
  const args = ['run', '--format', 'json'];
  if (reportOnly) args.push('--agent', 'plan');
  let platform;
  if (env.DEVFLEET_FORCE_OPENCODE === '1') {
    try { platform = openCodePlatformConfig(env); } catch {
      const reason = 'OpenCode 缺少有效的 XCMAX 网关地址、模型别名或专用密钥';
      throw Object.assign(new Error(reason), { stderr: reason });
    }
    args.push('--model', platform.model);
    log?.('OpenCode 平台模型 ' + platform.model);
  }
  const childEnv = {
      ...env,
      OPENCODE_DISABLE_PROJECT_CONFIG: 'true',
      OPENCODE_DISABLE_AUTOUPDATE: 'true',
      ...(platform ? { OPENCODE_CONFIG_CONTENT: JSON.stringify(platform) } : {}),
      ...(reportOnly ? { OPENCODE_PERMISSION: '{"edit":"deny","bash":"deny","task":"deny","external_directory":"deny"}' } : {}),
  };
  if (log) return runOpenCodeLive(executable, cwd, prompt, childEnv, { log, reportOnly, platform, timeoutMs });
  const run = execute(executable, args, {
    cwd, timeout: timeoutMs, maxBuffer: 10 * 1024 * 1024, windowsHide: true, env: childEnv,
  });
  streamCliOutput(run.child, 'opencode', log);
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
