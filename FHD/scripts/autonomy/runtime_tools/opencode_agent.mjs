import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { accessSync, constants, existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import { delimiter, dirname, join, resolve, sep } from 'node:path';
import { createInterface } from 'node:readline';
import { Readable } from 'node:stream';
import { fileURLToPath } from 'node:url';

const entry = fileURLToPath(import.meta.url);

function restrictedUserNamespaces() {
  if (process.platform !== 'linux') return false;
  const path = '/proc/sys/kernel/apparmor_restrict_unprivileged_userns';
  return existsSync(path) && readFileSync(path, 'utf8').trim() === '1';
}

// SRT 0.0.83's fixed helper first tries its PID/mount setup in bwrap's userns.
// Ubuntu's AppArmor policy strips capabilities from its nested-userns fallback.
// This is not a host privilege grant: bwrap creates the private userns first.
export function privateUserNamespaceArgs(args, { restricted, uid, euid }) {
  const end = args.indexOf('--');
  const flags = args.slice(0, end < 0 ? args.length : end);
  const profiles = flags.flatMap((flag, index) => flag === '--args' ? [index] : []);
  if (profiles.length > 1 || (profiles.length === 1 && flags[profiles[0] + 1] !== '9')) {
    throw new Error('opencode_unexpected_bwrap_profile_fd');
  }
  if (!restricted || (args.length === 1 && ['--version', '--help'].includes(args[0]))) return [...args];
  const drop = flags.indexOf('--cap-drop'), proc = flags.indexOf('--proc');
  if (!Number.isSafeInteger(uid) || uid < 1 || euid !== uid || end < 0
      || !['--unshare-user', '--unshare-pid', '--unshare-net', '--die-with-parent'].every(flag => flags.includes(flag))
      || drop < 0 || flags[drop + 1] !== 'ALL' || proc < 0 || flags[proc + 1] !== '/proc'
      || ['--cap-add', '--uid', '--gid', '--userns', '--userns2', '--as-pid-1'].some(flag => flags.includes(flag))) {
    throw new Error('opencode_private_user_namespace_required');
  }
  return [...flags, '--cap-add', 'CAP_SYS_ADMIN', ...args.slice(end)];
}

export function privateUserNamespaceLauncher(node, bwrap) {
  const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  // Native exec preserves SRT's anonymous read-only mount profile on fd 9
  // and --die-with-parent; no Node supervisor may outlive SRT's outer shell.
  return `#!/usr/bin/bash
set -eu
if ${quote(node)} ${quote(entry)} --sandbox-bwrap-check "$@"; then
  exec ${quote(bwrap)} "$@"
else
  status=$?
  [[ $status == 42 ]] || exit "$status"
fi
flags=()
while (( $# )); do
  if [[ $1 == -- ]]; then
    exec ${quote(bwrap)} "\${flags[@]}" --cap-add CAP_SYS_ADMIN "$@"
  fi
  flags+=("$1")
  shift
done
exit 1
`;
}

function trustedSystemExecutable(path) {
  const actual = realpathSync(path), stat = statSync(actual);
  accessSync(actual, constants.X_OK);
  if (!stat.isFile() || stat.uid !== 0 || (stat.mode & 0o6022)) throw new Error('opencode_untrusted_system_executable');
  return actual;
}

export function assertLinuxWorkloadIsolation(status) {
  const field = name => status.match(new RegExp('^' + name + ':\\s*(\\S+)', 'm'))?.[1];
  const namespacePids = status.match(/^NSpid:[ \t]*([^\n]*)/m)?.[1].trim();
  if (!['CapEff', 'CapPrm', 'CapAmb'].every(name => /^0+$/.test(field(name) || ''))
      || field('NoNewPrivs') !== '1' || field('Seccomp') !== '2'
      // A procfs mounted in an outer PID namespace exposes multiple NSpid
      // values. SRT tolerates a refused remount; this adapter must not.
      || !/^[1-9][0-9]*$/.test(namespacePids || '')
      || !/^[0-9a-f]+$/i.test(field('CapInh') || '')
      || (BigInt('0x' + field('CapInh')) & ~(1n << 21n)) !== 0n) {
    throw new Error('opencode_workload_isolation_required');
  }
}

export function openCodeSandboxEntry(env = process.env) {
  const [major, minor] = process.versions.node.split('.').map(Number);
  // The pinned Windows sandbox does not forward this worker's model environment.
  // Do not replace the native configuration/session checks with its CLI fallback.
  if (!['linux', 'darwin'].includes(process.platform)
      || major < 22 || (major === 22 && minor < 12)) {
    return undefined;
  }
  const installed = join(dirname(entry), 'node_modules', '@anthropic-ai', 'sandbox-runtime', 'dist', 'cli.js');
  const configured = env.DEVFLEET_OPENCODE_SANDBOX_ENTRY?.trim() || installed;
  try {
    const cli = realpathSync(configured);
    const manifest = JSON.parse(readFileSync(join(dirname(cli), '..', 'package.json'), 'utf8'));
    return manifest.name === '@anthropic-ai/sandbox-runtime' && manifest.version === '0.0.83' ? cli : undefined;
  } catch {
    return undefined;
  }
}

export function openCodeGatewayUrl(env) {
  const gateway = new URL(env.PARA_PLATFORM_GATEWAY_URL || '');
  if (gateway.protocol !== 'https:' || gateway.username || gateway.password || gateway.search || gateway.hash
      || !gateway.pathname.replace(/\/$/, '').endsWith('/v1')) {
    throw new Error('OpenCode 缺少有效的 XCMAX Responses 网关地址');
  }
  return gateway.href.replace(/\/$/, '');
}

export function openCodePlatformConfig(env) {
  const gateway = openCodeGatewayUrl(env);
  const model = env.PARA_OPENCODE_MODEL?.trim();
  if (!model || !/^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}$/.test(model) || !env.OPENCODE_API_KEY?.trim()
      || (env.PARA_PLATFORM_POOL === '1' && model !== env.PARA_PLATFORM_MODEL)) {
    throw new Error('OpenCode 缺少有效的 XCMAX 网关地址、模型别名或专用密钥');
  }
  return {
    model: 'xcmax/' + model,
    small_model: 'xcmax/' + model,
    enabled_providers: ['xcmax'],
    provider: { xcmax: { npm: '@ai-sdk/openai', name: 'XCMAX', whitelist: [model],
      options: { baseURL: gateway, apiKey: '{env:OPENCODE_API_KEY}' },
      models: { [model]: { id: model, name: model, provider: { npm: '@ai-sdk/openai' } } } } },
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

export function isOpenCodeReady(env = process.env) {
  if (process.platform === 'linux' && (!process.getuid?.() || process.geteuid?.() !== process.getuid())) return false;
  if (!openCodeExecutable(env) || !openCodeSandboxEntry(env)) return false;
  try { openCodePlatformConfig(env); return true; } catch { return false; }
}

function events(stdout = '') {
  return stdout.split(/\r?\n/).flatMap(line => {
    try { return [JSON.parse(line)]; } catch { return []; }
  });
}

export async function runOpenCodeLive(executable, cwd, prompt, env, options) {
  options = { ...options, log: options.log || (() => {}) };
  const password = randomUUID();
  const eventAbort = new AbortController();
  const signal = AbortSignal.any([AbortSignal.timeout(options.timeoutMs), eventAbort.signal]);
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
    const request = async (route, body, requestSignal = signal) => {
      const result = await fetch(base + route, {
        signal: requestSignal, headers: { ...headers, 'content-type': 'application/json' },
        ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}),
      });
      if (!result.ok) throw new Error('OpenCode HTTP ' + result.status + ' ' + (await result.text()).slice(0, 700));
      return result;
    };
    if (options.platform) {
      const effective = await (await request('/config')).json();
      const provider = effective.provider?.xcmax;
      const alias = env.PARA_OPENCODE_MODEL.trim();
      const model = provider?.models?.[alias];
      if (effective.model !== options.platform.model || effective.small_model !== options.platform.small_model
          || JSON.stringify(effective.enabled_providers) !== '["xcmax"]'
          || JSON.stringify(provider?.whitelist) !== JSON.stringify([alias])
          || provider?.npm !== '@ai-sdk/openai' || model?.provider?.npm !== '@ai-sdk/openai'
          || model?.id !== alias
          || provider?.options?.baseURL !== options.platform.provider.xcmax.options.baseURL
          || provider?.options?.apiKey !== env.OPENCODE_API_KEY
          || Object.keys(provider?.options?.headers || {}).length || Object.keys(model?.headers || {}).length) {
        throw new Error('opencode_platform_binding_mismatch');
      }
    }
    const session = await (await request('/session', { title: 'Para task',
      ...(options.reportOnly ? { permission: [
        { permission: '*', pattern: '*', action: 'deny' },
        ...['read', 'glob', 'grep', 'list'].map(permission => ({ permission, pattern: '*', action: 'allow' })),
      ] } : {}),
    })).json();
    const textParts = new Set();
    const handledPermissions = new Set();
    stream = Readable.fromWeb((await request('/event')).body);
    stream.on('error', () => {}); // Request/timeout reports the final status.
    const lines = createInterface({ input: stream });
    lines.on('line', line => {
      if (!line.startsWith('data:')) return;
      const event = events(line.slice(5).trim())[0];
      const fields = event?.properties;
      if (!fields || (fields.sessionID || fields.part?.sessionID) !== session.id) return;
      if (event.type === 'permission.asked') {
        if (!fields.id || handledPermissions.has(fields.id)) return;
        handledPermissions.add(fields.id);
        flush();
        options.log('[OpenCode] 已拒绝需要交互批准的工具请求');
        const replySignal = AbortSignal.any([signal, AbortSignal.timeout(5000)]);
        request('/permission/' + encodeURIComponent(fields.id) + '/reply', { reply: 'reject' }, replySignal)
          .catch(() => eventAbort.abort(new Error('OpenCode 未确认权限拒绝')));
        return;
      }
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
    if (eventAbort.signal.aborted) error = eventAbort.signal.reason;
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

function runtimeReadPath(executable) {
  const marker = sep + 'node_modules' + sep;
  const moduleRoot = executable.indexOf(marker);
  return moduleRoot < 0 ? executable : executable.slice(0, moduleRoot + marker.length - 1);
}

export function sandboxSettings(cwd, temp, executable, node, gateway, reportOnly, runtime) {
  const applySeccomp = process.platform === 'linux'
    ? join(dirname(runtime), '..', 'vendor', 'seccomp', process.arch, 'apply-seccomp')
    : undefined;
  if (applySeccomp) accessSync(applySeccomp, constants.X_OK);
  const systemPaths = process.platform === 'darwin'
    ? ['/System', '/usr/lib', '/usr/share', '/usr/bin', '/bin', '/private/etc/ssl',
      '/private/etc/hosts', '/private/var/db/timezone', '/Library/Preferences/SystemConfiguration']
    : ['/usr', '/lib', '/lib64', '/bin', '/dev/null', '/dev/urandom', '/etc/ssl',
      '/etc/hosts', '/etc/resolv.conf', '/etc/nsswitch.conf', '/etc/ld.so.cache'];
  return {
    ...(applySeccomp ? { seccomp: { applyPath: applySeccomp } } : {}),
    allowNestedUserNamespaces: false,
    network: {
      allowedDomains: [`${gateway.hostname}:${gateway.port || 443}`, 'registry.npmjs.org:443'],
      deniedDomains: [],
      allowAllUnixSockets: false,
      // Linux gives the two processes a private loopback namespace.
      allowLocalBinding: process.platform === 'darwin',
    },
    filesystem: {
      denyRead: ['/'],
      allowRead: [...systemPaths.filter(path => existsSync(path)), cwd, temp, entry,
        node, runtimeReadPath(executable), ...(applySeccomp ? [applySeccomp] : [])],
      allowWrite: reportOnly ? [temp] : [cwd, temp],
      denyWrite: [join(cwd, '.git'), join(cwd, '.devfleet'), '/tmp/claude', '/private/tmp/claude'],
    },
  };
}

function agentEnvironment(env, temp, platform, reportOnly) {
  return {
    PATH: env.PATH,
    XDG_CONFIG_HOME: join(temp, 'config'),
    XDG_CACHE_HOME: join(temp, 'cache'),
    XDG_DATA_HOME: join(temp, 'data'),
    XDG_STATE_HOME: join(temp, 'state'),
    TMPDIR: temp,
    CLAUDE_CODE_TMPDIR: temp,
    OPENCODE_CONFIG_CONTENT: JSON.stringify(platform),
    OPENCODE_API_KEY: env.OPENCODE_API_KEY,
    PARA_OPENCODE_MODEL: env.PARA_OPENCODE_MODEL,
    OPENCODE_DISABLE_PROJECT_CONFIG: 'true',
    OPENCODE_DISABLE_AUTOUPDATE: 'true',
    OPENCODE_DISABLE_MODELS_FETCH: 'true',
    OPENCODE_PERMISSION: JSON.stringify({
      '*': 'deny', read: 'allow', glob: 'allow', grep: 'allow', list: 'allow',
      todoread: 'allow', todowrite: 'allow', edit: reportOnly ? 'deny' : 'allow',
      bash: 'deny', task: 'deny', external_directory: 'deny',
    }),
  };
}

export async function runOpenCodeAgent(cwd, prompt, {
  env, timeoutMs, reportOnly, log, executable = openCodeExecutable(env),
}) {
  const sandbox = openCodeSandboxEntry(env);
  if (!executable || !sandbox) {
    const reason = 'OpenCode 需要 Linux/macOS 文件系统沙箱、Node 22.12+ 和已安装的 CLI';
    throw Object.assign(new Error(reason), { code: 'ENOENT', stderr: reason });
  }
  if (process.platform === 'linux' && (!process.getuid?.() || process.geteuid?.() !== process.getuid())) {
    throw new Error('opencode_private_user_namespace_requires_non_root');
  }
  const platform = openCodePlatformConfig(env);
  const gateway = new URL(env.PARA_PLATFORM_GATEWAY_URL);
  const workspace = realpathSync(cwd);
  const cli = realpathSync(executable);
  const node = realpathSync(process.execPath);
  const systemTemp = realpathSync(tmpdir());
  const scratchRoot = /^\/(?:private\/)?tmp\/claude(?:\/|$)/.test(systemTemp)
    ? realpathSync('/tmp')
    : systemTemp;
  const temp = await mkdtemp(join(scratchRoot, 'para-opencode-'));
  const policy = join(temp, 'sandbox.json');
  try {
    const settings = sandboxSettings(workspace, temp, cli, node, gateway, reportOnly, sandbox);
    const childEnv = agentEnvironment(env, temp, platform, reportOnly);
    if (restrictedUserNamespaces()) {
      // Only the fixed SRT builder reaches this entry. Its outer bash/socat
      // briefly share the private-namespace cap; no task text or startup hooks
      // enter their commands. The helper hides them behind a fresh PID /proc,
      // clears ambient caps, then enforces NNP and both seccomp filters.
      const bwrap = trustedSystemExecutable('/usr/bin/bwrap');
      trustedSystemExecutable('/usr/bin/bash');
      settings.socatPath = trustedSystemExecutable('/usr/bin/socat');
      childEnv.PATH = '/usr/bin:/bin:' + (childEnv.PATH || '');
      settings.bwrapPath = join(temp, 'bwrap');
      await writeFile(settings.bwrapPath, privateUserNamespaceLauncher(node, bwrap), { mode: 0o700 });
    }
    await writeFile(policy, JSON.stringify(settings), {
      mode: 0o600,
    });
    log?.('OpenCode 平台模型 ' + platform.model);
    return await new Promise((resolve, reject) => {
      const child = spawn(node, [sandbox, '--settings', policy, '--', node, entry, '--sandbox-worker'], {
        cwd: workspace,
        env: childEnv,
        stdio: ['pipe', 'pipe', 'pipe'],
        signal: AbortSignal.timeout(timeoutMs + 5000),
      });
      let result;
      let error = '';
      const lines = createInterface({ input: child.stdout });
      child.stderr.setEncoding('utf8').on('data', chunk => { error = (error + chunk).slice(-1000); });
      lines.on('line', line => {
        const event = events(line)[0];
        if (event?.type === 'log') log?.(event.text);
        if (event?.type === 'result') result = event.text;
        if (event?.type === 'error') error = event.text;
      });
      child.once('error', reject);
      child.once('close', code => {
        if (code === 0 && typeof result === 'string') resolve(result);
        else {
          const reason = error.trim() || `OpenCode 沙箱执行退出 (${code})`;
          reject(Object.assign(new Error(reason), { stderr: reason }));
        }
      });
      child.stdin.on('error', () => {}); // The child exit carries sandbox setup failures.
      child.stdin.end(JSON.stringify({ executable: cli, prompt, reportOnly, timeoutMs, workloadPath: env.PATH }));
    });
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
}

if (process.argv[1] && resolve(process.argv[1]) === entry && process.argv[2] === '--sandbox-bwrap-check') {
  try {
    if (Object.keys(process.env).some(key => /^(BASH_ENV|ENV|SHELLOPTS|BASHOPTS|PS4|BASH_FUNC_.*|LD_.*|NODE_OPTIONS|NODE_PATH)$/.test(key))) {
      throw new Error('opencode_untrusted_initialization_hook');
    }
    const original = process.argv.slice(3);
    const args = privateUserNamespaceArgs(original, {
      restricted: restrictedUserNamespaces(), uid: process.getuid?.(), euid: process.geteuid?.(),
    });
    trustedSystemExecutable('/usr/bin/bwrap');
    // The shell consumes this decision, then execs bwrap without a new parent.
    process.exitCode = args.length === original.length ? 0 : 42;
  } catch (error) {
    process.stderr.write(error.message + '\n');
    process.exitCode = 1;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === entry && ['--sandbox-worker', '--task'].includes(process.argv[2])) {
  const nativeTask = process.argv[2] === '--task';
  const emit = (type, text) => {
    const event = nativeTask && type === 'log' ? { type: 'text', part: { text } }
      : nativeTask && type === 'error' ? { type, error: { data: { message: text } } } : { type, text };
    process.stdout.write(JSON.stringify(event) + '\n');
  };
  try {
    if (!nativeTask && process.platform === 'linux') assertLinuxWorkloadIsolation(readFileSync('/proc/self/status', 'utf8'));
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    const { executable, prompt, reportOnly, timeoutMs, workloadPath } = JSON.parse(Buffer.concat(chunks).toString());
    // Restore the caller's toolchain only after the trusted initialization has
    // dropped its capabilities and the private PID/seccomp checks have passed.
    if (!nativeTask && typeof workloadPath === 'string') process.env.PATH = workloadPath;
    const log = text => emit('log', text);
    const result = nativeTask
      ? await runOpenCodeAgent(process.cwd(), prompt, { env: process.env, executable, reportOnly, timeoutMs, log })
      : await runOpenCodeLive(executable, process.cwd(), prompt, process.env, {
        reportOnly, timeoutMs, platform: JSON.parse(process.env.OPENCODE_CONFIG_CONTENT), log,
      });
    emit('result', result);
  } catch (error) {
    emit('error', error.message);
    process.exitCode = 1;
  }
}
