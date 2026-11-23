/** Trusted, per-task embedding of SRT. Only this host process holds the model key. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync, realpathSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const MAX_REQUEST_BYTES = 8 * 1024 * 1024;
const deny = () => ({ action: 'deny', reason: 'opencode_gateway_request_not_admitted' });

function gatewayIdentity(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash
      || url.hostname.endsWith('.') || !url.pathname.replace(/\/$/, '').endsWith('/v1')) {
    throw new Error('opencode_gateway_invalid');
  }
  return { url, path: url.pathname.replace(/\/$/, ''),
    host: url.hostname.replace(/^\[|\]$/g, ''), port: Number(url.port || 443) };
}

async function requestJson(request) {
  if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('content-type') || '')
      || request.headers.has('content-encoding') || !request.body) return undefined;
  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_REQUEST_BYTES) return undefined;
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return undefined;
  } finally {
    // The upstream tee has a separate reader. Never wait for its cancellation.
    reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

/** SRT's official request hook injects only a header, never sentinel bytes in a prompt. */
export function gatewayRequestFilter({ gateway, model, key }) {
  const identity = gatewayIdentity(gateway);
  if (typeof key !== 'string' || !/^[\x21-\x7e]+$/.test(key)
      || typeof model !== 'string' || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(model)) {
    throw new Error('opencode_gateway_credential_invalid');
  }
  return async (request, info) => {
    if (info?.scheme !== 'https' || info.requestTargetIsAmbiguous) return deny();
    const url = new URL(request.url);
    const host = url.hostname.replace(/^\[|\]$/g, '');
    if (url.protocol !== 'https:' || url.username || url.password || url.hash
        || info.target?.host !== host || info.target?.port !== Number(url.port || 443)) return deny();
    const removeHeaders = [...request.headers.keys()].filter(name => ![
      'accept', 'accept-encoding', 'content-type', 'content-length', 'user-agent',
    ].includes(name));
    // OpenCode resolves its pinned provider SDK here. No credentials, cookies,
    // proxy routing headers or write methods may accompany those downloads.
    if (host === 'registry.npmjs.org' && Number(url.port || 443) === 443) {
      if (!['GET', 'HEAD'].includes(request.method) || await info.unshownBody?.()) return deny();
      return { action: 'allow', removeHeaders };
    }
    if (url.origin !== identity.url.origin || host !== identity.host || url.search
        || info.requestTarget !== url.pathname) return deny();
    if (request.method === 'POST' && url.pathname === identity.path + '/responses') {
      const body = await requestJson(request);
      if (!body || body.model !== model) return deny();
    } else if (request.method !== 'GET' || url.pathname !== identity.path + '/models'
        || await info.unshownBody?.()) return deny();
    return { action: 'allow', removeHeaders,
      setHeaders: [['authorization', 'Bearer ' + key]] };
  };
}

export function controllerSettings({ settings, gateway, model }, key) {
  const { url, port } = gatewayIdentity(gateway);
  return { ...settings, allowNestedUserNamespaces: false,
    credentials: { envVars: [{ name: 'OPENCODE_API_KEY', mode: 'deny' }] },
    network: {
      allowedDomains: [`${url.hostname}:${port}`, 'registry.npmjs.org:443'],
      deniedDomains: [], strictAllowlist: true, tlsTerminate: {},
      allowAllUnixSockets: false, allowLocalBinding: process.platform === 'darwin',
      requireHostMatch: true, refuseOpaqueTunnels: true,
      stripResponseHeaders: ['authorization', 'proxy-authorization', 'x-api-key', 'set-cookie', 'set-cookie2'],
      filterRequest: gatewayRequestFilter({ gateway, model, key }),
    } };
}

// wrapWithSandbox deliberately accepts a shell command. Quote each trusted argv
// element independently; neither a path nor a prompt becomes shell program text.
const shellQuote = value => "'" + value.replace(/'/g, "'\\''") + "'";

export async function runSandboxController(payload) {
  if (!['linux', 'darwin'].includes(process.platform) || !payload || !payload.settings
      || !Array.isArray(payload.command) || !payload.command.length
      || payload.command.some(value => typeof value !== 'string' || !value || value.includes('\0'))
      || typeof payload.workload !== 'object' || payload.workload === null
      || !Number.isSafeInteger(payload.timeoutMs) || payload.timeoutMs < 1
      || payload.timeoutMs > 2 * 60 * 60 * 1000) throw new Error('opencode_controller_input_invalid');
  const runtime = realpathSync(payload.runtime);
  const root = dirname(dirname(runtime));
  const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  if (manifest.name !== '@anthropic-ai/sandbox-runtime' || manifest.version !== '0.0.83') {
    throw new Error('opencode_controller_runtime_mismatch');
  }
  const key = process.env.OPENCODE_API_KEY;
  delete process.env.OPENCODE_API_KEY;
  const config = controllerSettings(payload, key);
  const { SandboxManager, SandboxRuntimeConfigSchema } = await import(pathToFileURL(join(root, 'dist', 'index.js')));
  const policy = SandboxRuntimeConfigSchema.parse(config);
  const workload = { ...payload.workload, credentialPlaceholder: 'xcmax-placeholder-' + randomUUID(),
    credentialDigest: createHash('sha256').update(key).digest('hex') };
  let child;
  let killTimer;
  const interrupted = new AbortController();
  const stop = () => {
    interrupted.abort();
    if (!child || child.exitCode !== null || child.signalCode !== null) return;
    try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already exited */ }
    killTimer ??= setTimeout(() => {
      try { process.kill(-child.pid, 'SIGKILL'); } catch { /* already exited */ }
    }, 2000);
    killTimer.unref();
  };
  const stopTimer = setTimeout(stop, payload.timeoutMs);
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  const signalListeners = new Map(['SIGINT', 'SIGTERM'].map(name => [name, new Set(process.listeners(name))]));
  try {
    try {
      await SandboxManager.initialize(policy);
    } finally {
      // SRT's standalone-CLI handlers reset immediately. This embedding owns a
      // child lifetime: removing deny mount points while it still runs weakens
      // the boundary. Take over only listeners added by this initialization;
      // pre-existing listeners and SRT's final process-exit cleanup stay intact.
      for (const [name, previous] of signalListeners) {
        for (const listener of process.listeners(name)) {
          if (!previous.has(listener)) process.removeListener(name, listener);
        }
      }
    }
    interrupted.signal.throwIfAborted();
    workload.sandboxPrivateKeyPath = SandboxManager.getMitmCA()?.keyPath;
    if (typeof workload.sandboxPrivateKeyPath !== 'string' || !workload.sandboxPrivateKeyPath.startsWith('/')) {
      throw new Error('opencode_controller_private_key_boundary_missing');
    }
    let commandPolicy;
    if (process.platform === 'linux') {
      const sockets = [...new Set([
        SandboxManager.getLinuxHttpSocketPath(), SandboxManager.getLinuxSocksSocketPath(),
      ])];
      if (sockets.some(path => typeof path !== 'string' || !path.startsWith('/') || !statSync(path).isSocket())) {
        throw new Error('opencode_controller_network_bridge_missing');
      }
      // SRT creates its Unix bridges under the controller's private TMPDIR.
      // Its later denyRead mounts can hide the earlier bridge binds. Re-expose
      // only the observed socket files for SRT's pre-seccomp socat relays; the
      // directory and CA key remain denied, and the workload still cannot open
      // Unix sockets. The filesystem profile is compiled at wrap time.
      commandPolicy = { filesystem: { ...policy.filesystem,
        allowRead: [...new Set([...(policy.filesystem?.allowRead || []), ...sockets])] } };
    }
    const command = await SandboxManager.wrapWithSandbox(payload.command.map(shellQuote).join(' '),
      '/bin/bash', commandPolicy, interrupted.signal);
    interrupted.signal.throwIfAborted();
    return await new Promise((resolveExit, reject) => {
      // SRT guarantees a composable simple command. Exec keeps the tracked PID
      // on the native wrapper; bwrap also uses --die-with-parent on Linux.
      child = spawn('exec ' + command, { shell: '/bin/sh', detached: true,
        stdio: ['pipe', 'inherit', 'inherit'] });
      child.once('error', reject);
      child.once('close', code => resolveExit(interrupted.signal.aborted ? 1 : code ?? 1));
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify(workload));
    });
  } finally {
    clearTimeout(stopTimer);
    clearTimeout(killTimer);
    process.off('SIGINT', stop);
    process.off('SIGTERM', stop);
    await SandboxManager.reset();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const chunks = [];
    let size = 0;
    for await (const chunk of process.stdin) {
      size += chunk.length;
      if (size > 16 * 1024 * 1024) throw new Error('opencode_controller_input_too_large');
      chunks.push(chunk);
    }
    process.exitCode = await runSandboxController(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  } catch {
    // Native errors and policy closures may contain host paths or credentials.
    process.stdout.write(JSON.stringify({ type: 'error', text: 'opencode_sandbox_controller_failed' }) + '\n');
    process.exitCode = 1;
  }
}
