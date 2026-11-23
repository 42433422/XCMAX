/** Fixed promptfoo CLI inside the repository's official SRT network/filesystem boundary. */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { assertLinuxWorkloadIsolation, assertOpenCodeHost,
  assertPrivateKeyUnreadable, sandboxSettings } from './opencode_agent.mjs';

const entry = fileURLToPath(import.meta.url);
const placeholder = 'xcmax-training-provider-placeholder';
const deny = () => ({ action: 'deny', reason: 'training_model_request_not_admitted' });
const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";

function pinnedPackage(executable, name, version) {
  const path = realpathSync(executable || '');
  for (let directory = dirname(path); directory !== dirname(directory); directory = dirname(directory)) {
    const manifest = join(directory, 'package.json');
    if (!existsSync(manifest)) continue;
    const value = JSON.parse(readFileSync(manifest, 'utf8'));
    if (value.name === name && value.version === version) return { root: directory, path };
  }
  throw new Error('training_runtime_version_mismatch');
}

export function trainerSpec({ config, output }, env = process.env) {
  const cli = pinnedPackage(env.PROMPTFOO_CLI, 'promptfoo', '0.126.0');
  const runtime = pinnedPackage(env.PROMPTFOO_SANDBOX_ENTRY, '@anthropic-ai/sandbox-runtime', '0.0.83');
  const endpoint = new URL(env.XCAGI_LLM_BASE_URL || '');
  const model = env.XCAGI_LLM_MODEL?.trim();
  if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || endpoint.search
      || endpoint.hash || endpoint.hostname.endsWith('.')
      || !model || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(model)) {
    throw new Error('training_approved_model_required');
  }
  const configPath = realpathSync(config), directory = dirname(configPath);
  const outputPath = resolve(output);
  if (dirname(outputPath) !== directory) throw new Error('training_result_directory_mismatch');
  const document = JSON.parse(readFileSync(configPath, 'utf8'));
  const approvedProvider = provider => provider?.id === 'openai:chat:' + model
    && provider?.config?.apiBaseUrl?.replace(/\/$/, '') === endpoint.href.replace(/\/$/, '')
    && provider.config.maxRetries === 0;
  if (!Array.isArray(document.providers) || document.providers.length !== 1
      || !approvedProvider(document.providers[0])
      || !approvedProvider(document.defaultTest?.options?.provider)
      || document.sharing !== false) throw new Error('training_provider_configuration_mismatch');
  const python = resolve(env.PROMPTFOO_PYTHON || '');
  const pythonpath = realpathSync(env.PYTHONPATH || '');
  if (!env.PROMPTFOO_PYTHON || !statSync(python).isFile() || !env.PYTHONPATH
      || !statSync(pythonpath).isDirectory()) throw new Error('training_python_runtime_required');
  return { cli, runtime, endpoint, model, configPath, outputPath, directory, python, pythonpath };
}

export function trainerEnvironment(spec, temp) {
  return {
    PATH: [...new Set([dirname(spec.python), dirname(process.execPath), '/usr/bin', '/bin'])].join(':'),
    CI: '1', TMPDIR: temp,
    XDG_CONFIG_HOME: join(temp, 'config'), XDG_CACHE_HOME: join(temp, 'cache'),
    XDG_DATA_HOME: join(temp, 'data'), XDG_STATE_HOME: join(temp, 'state'),
    PROMPTFOO_DISABLE_TELEMETRY: '1', PROMPTFOO_DISABLE_UPDATE: '1',
    PROMPTFOO_DISABLE_SHARING: '1', PROMPTFOO_DISABLE_REMOTE_GENERATION: '1',
    PROMPTFOO_SELF_HOSTED: '1', PROMPTFOO_INSECURE_SSL: '0',
    PROMPTFOO_CONFIG_DIR: join(temp, 'promptfoo'), PROMPTFOO_LOG_DIR: join(temp, 'logs'),
    PROMPTFOO_PYTHON: spec.python, PYTHONPATH: spec.pythonpath,
    XCAGI_TRAINING_DEFER_NATIVE_REPLAY: '1',
    PYTHONDONTWRITEBYTECODE: '1',
  };
}

export function trainerRequestFilter(spec, key) {
  if (typeof key !== 'string' || !/^[\x21-\x7e]+$/.test(key)) throw new Error('training_model_key_required');
  const host = spec.endpoint.hostname.replace(/^\[|\]$/g, '');
  const port = Number(spec.endpoint.port || 443);
  const path = spec.endpoint.pathname.replace(/\/$/, '') + '/chat/completions';
  return async (request, info) => {
    const url = new URL(request.url);
    if (info?.scheme !== 'https' || info.requestTargetIsAmbiguous || info.target?.host !== host
        || info.target?.port !== port || url.origin !== spec.endpoint.origin
        || request.method !== 'POST' || url.pathname !== path || url.search || url.hash
        || info.requestTarget !== path || request.headers.has('content-encoding')
        || !/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || '')
        || !request.body) return deny();
    const reader = request.body.getReader(), chunks = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 2_000_000) return deny();
        chunks.push(value);
      }
      if (JSON.parse(Buffer.concat(chunks).toString('utf8')).model !== spec.model) return deny();
    } catch {
      return deny();
    } finally {
      reader.cancel().catch(() => {});
      reader.releaseLock();
    }
    return { action: 'allow',
      removeHeaders: [...request.headers.keys()].filter(name => ![
        'accept', 'accept-encoding', 'content-type', 'content-length', 'user-agent',
      ].includes(name)),
      setHeaders: [['authorization', 'Bearer ' + key]],
    };
  };
}

export function trainerPolicy(spec, temp, key) {
  const settings = sandboxSettings(spec.directory, temp, spec.cli.path, process.execPath,
    spec.endpoint, false, spec.runtime.path);
  settings.filesystem.allowRead.push(dirname(entry), spec.pythonpath,
    dirname(dirname(spec.python)), dirname(dirname(realpathSync(spec.python))),
    // Native file employees import the host SDK, including its existing app dependencies.
    // Keep the adjacent source tree read-only; the FHD root/data/config stay denied.
    realpathSync(resolve(dirname(entry), '../../../app')));
  return { ...settings,
    credentials: { envVars: [{ name: 'OPENAI_API_KEY', mode: 'deny' }, { name: 'XCAGI_LLM_API_KEY', mode: 'deny' }] },
    network: { allowedDomains: [`${spec.endpoint.hostname}:${spec.endpoint.port || 443}`],
      deniedDomains: [], strictAllowlist: true, tlsTerminate: {},
      allowAllUnixSockets: false, allowLocalBinding: false,
      requireHostMatch: true, refuseOpaqueTunnels: true,
      stripResponseHeaders: ['authorization', 'proxy-authorization', 'x-api-key', 'set-cookie', 'set-cookie2'],
      filterRequest: trainerRequestFilter(spec, key),
    },
  };
}

export const trainerArguments = spec => ['eval', '-c', spec.configPath, '-o', spec.outputPath,
  '--no-cache', '--no-share', '--no-write', '--no-progress-bar', '--max-concurrency', '2'];

export async function runTrainerSandbox(options, env = process.env) {
  const spec = trainerSpec(options, env);
  // Reuse the same verified native host support boundary as the existing SRT consumer.
  assertOpenCodeHost();
  const [major, minor] = process.versions.node.split('.').map(Number);
  if (major < 22 || (major === 22 && minor < 12)) throw new Error('training_node_22_12_required');
  const { SandboxManager, SandboxRuntimeConfigSchema } = await import(pathToFileURL(join(spec.runtime.root, 'dist/index.js')));
  const timeoutMs = options.timeoutMs ?? 10 * 60 * 1000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 20 * 60 * 1000) {
    throw new Error('training_timeout_invalid');
  }
  const temp = await mkdtemp(join(tmpdir(), 'training-workload-'));
  const control = await mkdtemp(join(tmpdir(), 'training-controller-'));
  const originalTemp = process.env.TMPDIR;
  const signal = new AbortController();
  let child, killTimer;
  const stop = () => {
    signal.abort();
    if (!child || child.exitCode !== null || child.signalCode !== null) return;
    try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already closed */ }
    killTimer ??= setTimeout(() => {
      try { process.kill(-child.pid, 'SIGKILL'); } catch { /* already closed */ }
    }, 2000);
    killTimer.unref();
  };
  const timer = setTimeout(stop, timeoutMs);
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  const listeners = new Map(['SIGINT', 'SIGTERM'].map(name => [name, new Set(process.listeners(name))]));
  try {
    process.env.TMPDIR = control;
    const policy = SandboxRuntimeConfigSchema.parse(trainerPolicy(spec, temp, env.XCAGI_LLM_API_KEY));
    try {
      await SandboxManager.initialize(policy);
    } finally {
      // The embedding owns the child lifetime; reset only after the process exits.
      for (const [name, previous] of listeners) for (const listener of process.listeners(name)) {
        if (!previous.has(listener)) process.removeListener(name, listener);
      }
    }
    signal.signal.throwIfAborted();
    const keyPath = SandboxManager.getMitmCA()?.keyPath;
    if (typeof keyPath !== 'string') throw new Error('training_sandbox_ca_missing');
    let custom;
    if (process.platform === 'linux') {
      const sockets = [SandboxManager.getLinuxHttpSocketPath(), SandboxManager.getLinuxSocksSocketPath()];
      if (sockets.some(path => typeof path !== 'string' || !statSync(path).isSocket())) {
        throw new Error('training_sandbox_bridge_missing');
      }
      custom = { filesystem: { ...policy.filesystem, allowRead: [...policy.filesystem.allowRead, ...sockets] } };
    }
    const command = await SandboxManager.wrapWithSandbox(
      [process.execPath, entry, '--sandbox-worker'].map(quote).join(' '), '/bin/bash', custom, signal.signal);
    signal.signal.throwIfAborted();
    return await new Promise((resolveExit, reject) => {
      child = spawn('exec ' + command, { cwd: spec.directory, shell: '/bin/sh', detached: true,
        env: { ...trainerEnvironment(spec, temp), TMPDIR: control }, stdio: ['pipe', 'inherit', 'inherit'] });
      child.once('error', reject);
      child.once('close', code => resolveExit(signal.signal.aborted ? 1 : code ?? 1));
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({ cli: spec.cli.path, args: trainerArguments(spec), temp, keyPath }));
    });
  } finally {
    clearTimeout(timer); clearTimeout(killTimer);
    process.off('SIGINT', stop); process.off('SIGTERM', stop);
    await SandboxManager.reset();
    if (originalTemp === undefined) delete process.env.TMPDIR;
    else process.env.TMPDIR = originalTemp;
    await rm(temp, { recursive: true, force: true });
    await rm(control, { recursive: true, force: true });
  }
}

if (process.argv[1] && resolve(process.argv[1]) === entry) {
  try {
    if (process.argv[2] === '--sandbox-worker') {
      if (process.platform === 'linux') assertLinuxWorkloadIsolation(readFileSync('/proc/self/status', 'utf8'));
      const chunks = [];
      for await (const chunk of process.stdin) chunks.push(chunk);
      const workload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      assertPrivateKeyUnreadable(workload.keyPath);
      if (process.env.OPENAI_API_KEY || process.env.XCAGI_LLM_API_KEY) throw new Error('training_secret_reached_worker');
      process.env.OPENAI_API_KEY = placeholder;
      process.env.TMPDIR = workload.temp;
      process.argv = [process.execPath, workload.cli, ...workload.args];
      await import(pathToFileURL(workload.cli));
    } else {
      const { values } = parseArgs({ options: { config: { type: 'string' }, output: { type: 'string' } } });
      process.exitCode = await runTrainerSandbox(values);
    }
  } catch {
    process.stderr.write('training_sandbox_failed; no unsandboxed evaluation fallback\n');
    process.exitCode = 1;
  }
}
