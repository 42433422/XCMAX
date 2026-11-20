import { createInterface } from 'node:readline';

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

export function streamCliOutput(child, tool, log) {
  if (!log) return;
  let pending = '';
  let timer;
  let hasDeltas = false;
  const label = LABEL[tool] || tool;
  const send = (text, level = 'info') => {
    if (typeof text === 'string' && text.trim()) log('[' + label + '] ' + text.slice(0, 1500), level);
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
