import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { accessSync, constants, existsSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import { delimiter, dirname, join, resolve, sep } from 'node:path';
import { createInterface } from 'node:readline';
import { Readable } from 'node:stream';
import { fileURLToPath } from 'node:url';

const entry = fileURLToPath(import.meta.url);
export const OPENCODE_CREDENTIAL_ISOLATION = 'srt-0.0.83-header-only-platform-v1';

export function assertMaskedCredential(value, originalDigest) {
  if (typeof value !== 'string' || !value || !/^[0-9a-f]{64}$/.test(originalDigest || '')
      || createHash('sha256').update(value).digest('hex') === originalDigest) {
    throw new Error('opencode_non_exportable_credential_required');
  }
}

export function assertPrivateKeyUnreadable(path) {
  if (typeof path !== 'string' || !path.startsWith('/')) throw new Error('opencode_ca_boundary_missing');
  try {
    accessSync(path, constants.R_OK);
  } catch (error) {
    if (['ENOENT', 'EACCES', 'EPERM'].includes(error.code)) return;
    throw new Error('opencode_ca_boundary_unverified');
  }
  throw new Error('opencode_ca_private_key_readable');
}

function userNamespacesRestricted() {
  return [
    ['kernel/apparmor_restrict_unprivileged_userns', value => value === '0'],
    ['kernel/unprivileged_userns_clone', value => value === '1'],
    ['user/max_user_namespaces', value => /^[1-9][0-9]*$/.test(value)],
  ].some(([name, allowed]) => {
    const path = '/proc/sys/' + name;
    return existsSync(path) && !allowed(readFileSync(path, 'utf8').trim());
  });
}

export function assertOpenCodeHost({ platform = process.platform, uid = process.getuid?.(),
  euid = process.geteuid?.(), release, restricted } = {}) {
  if (platform === 'darwin') return;
  if (platform !== 'linux') throw new Error('opencode_host_requires_ubuntu_22_04_or_macos');
  // This is a product support boundary, not a request to weaken host AppArmor.
  // SRT's native userns/seccomp chain is not compatible with stock Ubuntu 26.
  release ??= readFileSync('/etc/os-release', 'utf8');
  restricted ??= userNamespacesRestricted();
  if (!/^ID=(?:ubuntu|"ubuntu"|'ubuntu')$/m.test(release)
      || !/^VERSION_ID=(?:22\.04|"22\.04"|'22\.04')$/m.test(release) || restricted) {
    throw new Error('opencode_linux_host_requires_ubuntu_22_04_without_userns_restrictions');
  }
  if (!Number.isSafeInteger(uid) || uid < 1 || euid !== uid) {
    throw new Error('opencode_private_user_namespace_requires_non_root');
  }
}

export function assertLinuxWorkloadIsolation(status) {
  const field = name => status.match(new RegExp('^' + name + ':\\s*(\\S+)', 'm'))?.[1];
  const namespacePids = status.match(/^NSpid:[ \t]*([^\n]*)/m)?.[1].trim();
  if (!['CapEff', 'CapPrm', 'CapAmb', 'CapInh'].every(name => /^0+$/.test(field(name) || ''))
      || field('NoNewPrivs') !== '1' || field('Seccomp') !== '2'
      // A procfs mounted in an outer PID namespace exposes multiple NSpid
      // values. SRT tolerates a refused remount; this adapter must not.
      || !/^[1-9][0-9]*$/.test(namespacePids || '')) {
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
    assertOpenCodeHost();
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
  const closed = new Promise(resolve => server.once('close', resolve));
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
    const lines = createInterface({ input: stream });
    lines.on('error', error => eventAbort.abort(error));
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
    const stop = setTimeout(() => {
      if (server.exitCode === null && server.signalCode === null) server.kill('SIGKILL');
    }, 2000);
    stop.unref();
    try {
      server.kill('SIGTERM');
      await closed; // Callers may only remove the workspace after the child releases it.
    } finally {
      clearTimeout(stop);
    }
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
      tlsTerminate: {},
      requireHostMatch: true,
      refuseOpaqueTunnels: true,
      allowAllUnixSockets: false,
      // Linux gives the two processes a private loopback namespace.
      allowLocalBinding: process.platform === 'darwin',
    },
    // The trusted controller injects Authorization through SRT's request hook.
    // Never enable generic masking: it substitutes secrets into request bodies.
    credentials: {
      envVars: [{ name: 'OPENCODE_API_KEY', mode: 'deny' }],
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
    PATH: process.platform === 'linux' ? '/usr/bin:/bin' : env.PATH,
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
  assertOpenCodeHost();
  const sandbox = openCodeSandboxEntry(env);
  if (!executable || !sandbox) {
    const reason = 'OpenCode 需要 Ubuntu 22.04/macOS 文件系统沙箱、Node 22.12+ 和已安装的 CLI';
    throw Object.assign(new Error(reason), { code: 'ENOENT', stderr: reason });
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
  // SRT writes its ephemeral CA private key under TMPDIR. Keep that control
  // directory outside every workload read/write root; SRT exposes only the
  // public certificate/trust bundle through its own narrow read exceptions.
  const controlTemp = await mkdtemp(join(scratchRoot, 'para-opencode-control-'));
  try {
    const settings = sandboxSettings(workspace, temp, cli, node, gateway, reportOnly, sandbox);
    const childEnv = agentEnvironment(env, temp, platform, reportOnly);
    log?.('OpenCode 平台模型 ' + platform.model);
    return await new Promise((resolve, reject) => {
      const controller = join(dirname(entry), 'opencode_sandbox_controller.mjs');
      const child = spawn(node, [controller], {
        cwd: workspace,
        env: { ...childEnv, TMPDIR: controlTemp },
        stdio: ['pipe', 'pipe', 'pipe'],
        signal: AbortSignal.timeout(timeoutMs + 5000),
      });
      let result;
      let error = '';
      let processError;
      let killTimer;
      const lines = createInterface({ input: child.stdout });
      child.stderr.setEncoding('utf8').on('data', chunk => { error = (error + chunk).slice(-1000); });
      lines.on('line', line => {
        const event = events(line)[0];
        if (event?.type === 'log') log?.(event.text);
        if (event?.type === 'result') result = event.text;
        if (event?.type === 'error') error = event.text;
      });
      child.once('error', failure => {
        processError = failure;
        // AbortSignal emits its error before the process has closed. The
        // controller still owns the sandbox and may be terminating a worker;
        // keep its temporary directories until native close is observed.
        if (!child.pid) reject(failure);
        else {
          child.kill('SIGTERM');
          killTimer = setTimeout(() => child.kill('SIGKILL'), 5000);
          killTimer.unref();
        }
      });
      child.once('close', code => {
        clearTimeout(killTimer);
        lines.close();
        if (!processError && code === 0 && typeof result === 'string') resolve(result);
        else {
          const reason = error.trim() || processError?.message || `OpenCode 沙箱执行退出 (${code})`;
          reject(Object.assign(new Error(reason), { stderr: reason }));
        }
      });
      child.stdin.on('error', () => {}); // The child exit carries sandbox setup failures.
      child.stdin.end(JSON.stringify({ runtime: sandbox, settings,
        gateway: platform.provider.xcmax.options.baseURL, model: env.PARA_OPENCODE_MODEL,
        command: [node, entry, '--sandbox-worker'], timeoutMs,
        workload: { executable: cli, prompt, reportOnly, timeoutMs,
          workloadPath: env.PATH, workloadTemp: temp },
      }));
    });
  } finally {
    await rm(temp, { recursive: true, force: true });
    await rm(controlTemp, { recursive: true, force: true });
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
    const { executable, prompt, reportOnly, timeoutMs, workloadPath, workloadTemp,
      credentialPlaceholder, credentialDigest, sandboxPrivateKeyPath } = JSON.parse(Buffer.concat(chunks).toString());
    if (!nativeTask) {
      if (process.env.OPENCODE_API_KEY) throw new Error('opencode_model_secret_reached_workload');
      assertPrivateKeyUnreadable(sandboxPrivateKeyPath);
      assertMaskedCredential(credentialPlaceholder, credentialDigest);
      process.env.OPENCODE_API_KEY = credentialPlaceholder;
    }
    // Restore the caller's toolchain after native PID/seccomp/capability checks.
    if (!nativeTask && typeof workloadPath === 'string') process.env.PATH = workloadPath;
    if (!nativeTask) {
      if (typeof workloadTemp !== 'string' || !workloadTemp.startsWith('/')) throw new Error('opencode_workload_temp_required');
      process.env.TMPDIR = workloadTemp;
    }
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
