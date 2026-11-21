import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

const LABEL = { codex: 'Codex', cursor: 'Cursor', trae: 'TRAE', claude_code: 'Claude Code', opencode: 'OpenCode' };

function eventFromLine(line) {
  try { return JSON.parse(line); } catch { return null; }
}

function assistantText(event) {
  const content = event?.message?.content;
  if (typeof content === 'string') return content;
  return Array.isArray(content) ? content.filter(part => part?.type === 'text').map(part => part.text).join('') : '';
}

function errorText(event) {
  const error = event?.error;
  return error?.data?.message || error?.message || (typeof error === 'string' ? error : '') || event?.message;
}

export function cliResult(stdout) {
  const events = String(stdout || '').split(/\r?\n/).map(eventFromLine);
  const final = events.findLast(event => event?.type === 'result' && typeof event.result === 'string');
  if (final) return final.result.trim();
  return events.map(event => {
    if (event?.type === 'text') return event.part?.text;
    if (event?.type === 'item.completed' && event.item?.type === 'agent_message') return event.item.text;
    if (event?.type === 'assistant') return assistantText(event);
    return '';
  }).filter(Boolean).join('\n').trim();
}

/** Thin consumer of Codex 0.153.4's exec JSONL protocol; item failures may be recovered within a turn. */
export function createCodexTurnReceipt() {
  const receipt = { thread_id: null, turn_started: false, turn_completed: false,
    tool_calls: 0, tool_failures: 0, tool_results: [], omitted_tool_results: 0, usage: null };
  const activeTools = new Set();
  const toolTypes = new Set(['command_execution', 'file_change', 'mcp_tool_call', 'collab_tool_call']);
  let terminal = '';
  let protocolError = '';
  let failure = '';
  let diagnostic = '';
  let output = '';
  function observe(event, line = '') {
    if (!line.trim() && !event) return;
    if (!event || typeof event !== 'object' || typeof event.type !== 'string') {
      protocolError ||= 'codex_invalid_jsonl';
      return;
    }
    if (event.type === 'error') {
      // 0.153.4 drops ErrorNotification.will_retry from JSONL. A later completed
      // turn plus exit 0 is authoritative; intermediate transport errors are not.
      diagnostic = String(event.message || 'codex_error').slice(0, 800);
      if (terminal) protocolError ||= 'codex_error_after_terminal';
      return;
    }
    if (terminal) { protocolError ||= 'codex_event_after_terminal'; return; }
    if (event.type === 'thread.started') {
      if (receipt.thread_id || receipt.turn_started || typeof event.thread_id !== 'string' || !event.thread_id) {
        protocolError ||= 'codex_invalid_thread';
      } else receipt.thread_id = event.thread_id.slice(0, 128);
    } else if (event.type === 'turn.started') {
      if (!receipt.thread_id || receipt.turn_started) protocolError ||= 'codex_invalid_turn';
      receipt.turn_started = true;
    } else if (event.type === 'turn.failed') {
      terminal = 'failed';
      failure ||= String(event.error?.message || 'codex_turn_failed').slice(0, 800);
    } else if (event.type === 'turn.completed') {
      terminal = 'completed';
      const usage = event.usage;
      const required = ['input_tokens', 'cached_input_tokens', 'output_tokens'];
      const optional = ['cache_write_input_tokens', 'reasoning_output_tokens'];
      if (!receipt.turn_started || !usage
          || required.some(key => !Number.isSafeInteger(usage[key]) || usage[key] < 0)
          || optional.some(key => usage[key] !== undefined && (!Number.isSafeInteger(usage[key]) || usage[key] < 0))) {
        protocolError ||= 'codex_invalid_completion';
      } else {
        receipt.turn_completed = true;
        receipt.usage = Object.fromEntries([...required, ...optional]
          .filter(key => usage[key] !== undefined).map(key => [key, usage[key]]));
      }
    } else if (event.type.startsWith('item.')) {
      // Native config/deprecation warnings can precede thread/turn startup.
      if (event.type === 'item.completed' && event.item?.type === 'error') return;
      if (!receipt.turn_started || !event.item || typeof event.item.id !== 'string') {
        protocolError ||= 'codex_invalid_item';
        return;
      }
      const item = event.item;
      if (toolTypes.has(item.type)) {
        if (event.type === 'item.started') {
          if (activeTools.has(item.id)) protocolError ||= 'codex_duplicate_tool_start';
          activeTools.add(item.id);
          receipt.tool_calls += 1;
        } else if (event.type === 'item.completed') {
          if (!['completed', 'failed', 'declined'].includes(item.status)) {
            protocolError ||= 'codex_invalid_tool_completion';
          }
          activeTools.delete(item.id);
          if (item.status !== 'completed') receipt.tool_failures += 1;
          if (receipt.tool_results.length === 8) {
            receipt.tool_results.shift(); receipt.omitted_tool_results += 1;
          }
          receipt.tool_results.push({ id: item.id.slice(0, 64), type: item.type, status: item.status,
            ...(item.type === 'command_execution' ? {
              exit_code: Number.isInteger(item.exit_code) ? item.exit_code : null,
              command_sha256: typeof item.command === 'string'
                ? createHash('sha256').update(item.command).digest('hex') : null,
            } : {}) });
        }
      } else if (event.type === 'item.completed' && item.type === 'agent_message') {
        if (typeof item.text !== 'string') protocolError ||= 'codex_invalid_message';
        else output = item.text.slice(-10 * 1024 * 1024);
      }
    }
  }
  function finish({ exitCode, signal, timedOut = false, cancelled = false, executionStarted = true, launchError = '' }) {
    const reason = launchError || (timedOut ? 'codex_timeout' : cancelled ? 'codex_cancelled' : '')
      || failure || protocolError || (signal ? 'codex_process_signal' : '')
      || (exitCode !== 0 ? diagnostic || 'codex_process_exit' : '')
      || (!receipt.turn_completed ? diagnostic || 'codex_missing_completion' : '')
      || (activeTools.size ? 'codex_incomplete_tools' : '');
    const status = !reason ? 'completed' : !executionStarted ? 'not_started'
      : timedOut || cancelled || signal || protocolError || (!failure && exitCode === 0) ? 'unknown' : 'failed';
    return { ok: status === 'completed', output, executionStarted,
      receipt: { ...receipt, status, reason: reason || null, exit_code: exitCode,
        signal: signal || null, active_tools: activeTools.size } };
  }
  return { observe, finish };
}

/** Always require the native terminal event and process exit, including silent probes. */
export function runCodexCli({ executable, cwd, prompt, args, env, log, timeoutMs, signal, killGraceMs = 3000, cliVersion = null, versionCheckedAt = null }) {
  if (args[0] !== 'exec' || !Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('invalid_codex_invocation');
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(Object.assign(new Error('codex_cancelled_before_start'), { executionStarted: false })); return; }
    const grouped = process.platform !== 'win32';
    const child = spawn(executable, args.includes('--json') ? args : ['exec', '--json', ...args.slice(1)],
      { cwd, env, detached: grouped, stdio: ['pipe', 'pipe', 'pipe'] });
    const turn = createCodexTurnReceipt();
    let stderr = '';
    let started = false;
    let timedOut = false;
    let cancelled = false;
    let launchError = '';
    let stopping;
    const killGroup = value => {
      try { process.kill(-child.pid, value); }
      catch (error) { if (error.code !== 'ESRCH') launchError ||= 'codex_process_group_stop_failed'; }
    };
    const stop = () => {
      if (stopping || !child.pid) return;
      stopping = new Promise(done => {
        if (grouped) {
          killGroup('SIGTERM');
          setTimeout(() => { killGroup('SIGKILL'); done(); }, killGraceMs);
        } else {
          // Windows has no POSIX process groups. Its native tree termination must
          // run while the root PID still identifies its children.
          const killer = spawn(join(process.env.SystemRoot || process.env.SYSTEMROOT || 'C:\\Windows', 'System32', 'taskkill.exe'),
            ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
          killer.once('error', () => { launchError ||= 'codex_process_tree_stop_failed'; child.kill('SIGKILL'); });
          killer.once('close', code => {
            if (code !== 0 && child.exitCode === null && child.signalCode === null) {
              launchError ||= 'codex_process_tree_stop_failed'; child.kill('SIGKILL');
            }
            done();
          });
        }
      });
    };
    const abort = () => { cancelled = true; stop(); };
    const timer = setTimeout(() => { timedOut = true; stop(); }, timeoutMs);
    signal?.addEventListener('abort', abort, { once: true });
    child.once('spawn', () => { started = true; if (cancelled || timedOut) stop(); });
    child.once('error', error => { launchError = String(error.code || 'codex_spawn_error'); });
    child.stderr.setEncoding('utf8').on('data', chunk => { stderr = (stderr + chunk).slice(-4000); });
    child.stdin.on('error', error => { if (error.code !== 'EPIPE') { launchError ||= 'codex_input_error'; stop(); } });
    streamCliOutput(child, 'codex', log, turn.observe);
    child.once('close', async (exitCode, exitSignal) => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      // A child may exit on TERM while a tool still owns the pipes/workspace.
      // Finish the process-tree stop even if the direct child's exit arrived first.
      await stopping;
      const result = turn.finish({ exitCode, signal: exitSignal, timedOut, cancelled,
        executionStarted: started, launchError });
      result.receipt.cli_version = cliVersion;
      result.receipt.version_checked_at = versionCheckedAt;
      result.receipt.termination_method = stopping ? grouped ? 'posix_process_group' : 'windows_taskkill_tree' : null;
      if (!result.ok) result.output = `[codex exit=${exitCode}${exitSignal ? ` signal=${exitSignal}` : ''}]\n`
        + `${result.receipt.reason}${stderr.trim() ? '\n' + stderr.trim() : ''}`;
      log?.(`codex_execution_receipt=${JSON.stringify(result.receipt)}`, result.ok ? 'info' : 'warn');
      resolve(result);
    });
    child.stdin.end(prompt);
  });
}

export function streamCliOutput(child, tool, log, observe) {
  if (!log && !observe) return;
  let pending = '';
  let timer;
  let hasDeltas = false;
  const label = LABEL[tool] || tool;
  const send = (text, level = 'info') => {
    if (typeof text === 'string' && text.trim()) log?.('[' + label + '] ' + text.slice(0, 1500), level);
  };
  const flush = () => {
    clearTimeout(timer);
    timer = undefined;
    send(pending);
    pending = '';
  };
  const append = text => {
    if (typeof text !== 'string' || !text) return;
    pending += text;
    if (pending.length >= 1000) flush();
    else timer ??= setTimeout(flush, 150);
  };
  const stdout = createInterface({ input: child.stdout, crlfDelay: Infinity });
  stdout.on('line', line => {
    const event = eventFromLine(line);
    observe?.(event, line);
    const type = event?.type;
    if (!type) return;
    if (type === 'stream_event' && event.event?.delta?.type === 'text_delta') {
      hasDeltas = true;
      append(event.event.delta.text);
    } else if (type === 'assistant') {
      if (!hasDeltas) append(assistantText(event));
    } else if (type === 'text') {
      append(event.part?.text);
    } else if (type === 'item.completed' && event.item?.type === 'agent_message') {
      append(event.item.text);
      flush();
    } else if (type === 'turn.failed' || type === 'error' || (type === 'result' && (event.is_error || event.error || String(event.subtype || '').startsWith('error')))) {
      flush();
      send(errorText(event) || event.result || '执行失败', 'warn');
    } else if (type === 'tool_use' || type === 'tool_call' || (type === 'item.started' && event.item?.type === 'command_execution')) {
      flush();
      send('正在调用工具');
    } else if (type === 'step_finish' && Number.isFinite(event.part?.tokens?.input) && Number.isFinite(event.part?.tokens?.output)) {
      flush();
      send('模型用量：输入 ' + event.part.tokens.input + '，输出 ' + event.part.tokens.output + ' token');
    } else if (type === 'thread.started' || (type === 'system' && event.subtype === 'init')) {
      send('会话已启动');
    }
  });
  stdout.on('close', flush);
  const stderr = createInterface({ input: child.stderr, crlfDelay: Infinity });
  stderr.on('line', line => { flush(); send(line, 'warn'); });
}
