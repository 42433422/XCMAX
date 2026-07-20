const MAX_SUMMARY_CHARS = 800;

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
  let error = typeof lastResult.error === 'string' ? lastResult.error.trim() : '';
  if (!error && lastResult.is_error) {
    error = resultOutput || `Trae stream result is_error subtype=${lastResult.subtype || 'unknown'}`;
  }
  return {
    error,
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
  if (!summary && error?.message) summary = String(error.message).trim();
  if (!summary) summary = `Trae CLI exited${exitCode === null ? '' : ` with code ${exitCode}`}`;
  summary = summary.slice(0, MAX_SUMMARY_CHARS);
  const message = asText(error?.message).trim();
  return {
    exitCode,
    raw: `${structured.error}\n${stderr}\n${message}`.trim().toLowerCase(),
    subtype: structured.subtype,
    summary,
  };
}

export function isTraeProviderFailoverEligible(value) {
  const raw = typeof value === 'string'
    ? value.toLowerCase()
    : String(value?.raw || value?.summary || '').toLowerCase();
  if (!raw) return false;

  const policyFailures = [
    'content filter',
    'permission denied',
    'policy violation',
    'prompt rejected',
    'safety policy',
  ];
  if (policyFailures.some((pattern) => raw.includes(pattern))) return false;

  const providerFailures = [
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
    'service unavailable',
    'temporarily unavailable',
    'timed out',
    'too many requests',
  ];
  return providerFailures.some((pattern) => raw.includes(pattern));
}
