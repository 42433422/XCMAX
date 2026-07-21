const MAX_SUMMARY_CHARS = 800;

const POLICY_FAILURES = [
  'content filter',
  'permission denied',
  'policy violation',
  'prompt rejected',
  'safety policy',
];

const PROVIDER_FAILURES = [
  '429',
  '502',
  '503',
  '504',
  'authentication expired',
  'connection reset',
  'model usage has reached',
  'overloaded',
  'personal quota limit',
  'provider unavailable',
  'quota exceeded',
  'rate limit',
  'request timed out',
  'service unavailable',
  'stream disconnected',
  'temporarily unavailable',
  'timed out',
  'too many requests',
  'usage limit',
];

function asText(value) {
  if (Buffer.isBuffer(value)) return value.toString('utf8');
  return typeof value === 'string' ? value : '';
}

export function parseTraeStream(output) {
  let lastResult = null;
  for (const line of asText(output).split(/\r?\n/)) {
    const text = line.trim();
    if (!text.startsWith('{')) continue;
    try {
      const payload = JSON.parse(text);
      if (payload?.type === 'result') lastResult = payload;
    } catch {
      // Non-JSON diagnostic lines are allowed in stream-json output.
    }
  }
  if (!lastResult) return { error: '', output: '', subtype: '' };
  const resultOutput = typeof lastResult.result === 'string'
    ? lastResult.result
    : typeof lastResult.output === 'string'
      ? lastResult.output
      : '';
  return {
    error: typeof lastResult.error === 'string' ? lastResult.error.trim() : '',
    output: resultOutput.trim(),
    subtype: String(lastResult.subtype || ''),
  };
}

export function describeTraeFailure(error) {
  const stdout = asText(error?.stdout);
  const stderr = asText(error?.stderr).trim();
  const structured = parseTraeStream(stdout);
  const exitCode = Number.isInteger(error?.code) ? error.code : null;
  let summary = structured.error;
  if (!summary && stderr) summary = stderr.split(/\r?\n/).slice(-8).join('\n').trim();
  if (!summary) summary = `Trae CLI exited${exitCode === null ? '' : ` with code ${exitCode}`}`;
  summary = summary.slice(0, MAX_SUMMARY_CHARS);
  return {
    exitCode,
    raw: `${structured.error}\n${stderr}`.trim().toLowerCase(),
    subtype: structured.subtype,
    summary,
  };
}

export function isTraeProviderFailoverEligible(value) {
  const raw = typeof value === 'string'
    ? value.toLowerCase()
    : String(value?.raw || value?.summary || '').toLowerCase();
  if (!raw) return false;

  if (POLICY_FAILURES.some((pattern) => raw.includes(pattern))) return false;
  return PROVIDER_FAILURES.some((pattern) => raw.includes(pattern));
}

export function formatCodexNonZeroOutput(
  { code, signal = '', stdout = '', stderr = '' },
  maxChars = 4000,
) {
  const header = `[codex exit=${code}${signal ? ` signal=${signal}` : ''}]`;
  const diagnostic = [asText(stdout).trim(), asText(stderr).trim()].filter(Boolean).join('\n').trim();
  if (!diagnostic) return header;
  const full = `${header}\n${diagnostic}`;
  if (full.length <= maxChars) return full;
  const marker = '\n[diagnostic tail]\n';
  const tailChars = Math.max(0, maxChars - header.length - marker.length);
  return `${header}${marker}${diagnostic.slice(-tailChars)}`;
}

export function describeCodexFailure(output) {
  const text = asText(output).trim();
  const lines = text.split(/\r?\n/).filter(Boolean);
  const tail = lines.slice(-8).join('\n').trim();
  return {
    raw: tail.toLowerCase(),
    summary: (tail || 'Codex CLI exited non-zero').slice(0, MAX_SUMMARY_CHARS),
  };
}

export function isCodexProviderFailoverEligible(value) {
  return isTraeProviderFailoverEligible(value);
}
