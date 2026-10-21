/**
 * Codex 模型网关：同一执行器内的有序模型候选 + 探活 + 自动降级。
 *
 * - 候选顺序：任务提示里的 `codex_model_candidates:` 行 > DEVFLEET_CODEX_MODEL_CANDIDATES
 *   > 默认 gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna（是否真实可用以探活为准）。
 * - 鉴权：DEVFLEET_CODEX_API_KEY_ENV 指定的变量（默认 OPENAI_API_KEY，其次 CODEX_API_KEY）
 *   有值时只给本次 codex exec 子进程注入 CODEX_API_KEY；缺失时回退 ChatGPT 登录并在日志标注。
 *   日志只写变量名，从不写值。
 * - 遇到“模型不支持 / 模型不存在 / 额度耗尽”换下一个候选重试同一任务；其他失败原样返回，
 *   交给既有的执行器回退链 / 超时逻辑（不在这里重复实现）。
 * - DEVFLEET_CODEX_MODEL_GATEWAY=0 关闭自动降级；角色显式模型仍作为单候选传给 CLI。
 */

export const DEFAULT_CODEX_MODEL_CANDIDATES = Object.freeze(['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']);
export const CODEX_MODELS_TRIED_MARKER = 'codex_models_tried=';

const MODEL_UNAVAILABLE_PATTERNS = [
  /model[^\n]{0,80}not supported/i,
  /not supported[^\n]{0,80}chatgpt account/i,
  /unsupported[_ ]model/i,
  /model_not_found/i,
  /model[^\n]{0,60}does not exist/i,
  /does not have access to (the )?model/i,
  /invalid model/i,
  /unknown model/i,
];
const QUOTA_PATTERNS = [
  /insufficient_quota/i,
  /exceeded your current quota/i,
  /usage limit (reached|exceeded)/i,
  /you'?ve hit your usage limit/i,
  /quota (exceeded|exhausted)/i,
];

function asText(value) {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : String(value);
}

function splitModels(raw) {
  return asText(raw)
    .split(/[,\s>]+/)
    .map((s) => s.trim())
    .filter((s) => /^[A-Za-z0-9._:\-/]+$/.test(s));
}

function dedupe(list) {
  const seen = new Set();
  return list.filter((m) => (seen.has(m) ? false : (seen.add(m), true)));
}

export function modelGatewayEnabled(env = process.env) {
  return asText(env.DEVFLEET_CODEX_MODEL_GATEWAY).trim() !== '0';
}

/** Only the final dispatcher context supplies controls; quoted task text cannot override it. */
function loopContext(prompt) {
  const text = asText(prompt);
  const headers = [...text.matchAll(/^MODstore loop context:\s*$/gm)];
  const header = headers.at(-1);
  if (!header) return null;
  const tail = text.slice(header.index + header[0].length);
  const fields = new Map();
  for (const line of tail.split(/\r?\n/).filter((value) => value.trim())) {
    const field = line.match(/^- ([a-z_]+):\s*(.*)$/);
    if (!field || fields.has(field[1])) {
      if (/^- incident_execution_budget:/m.test(tail)) throw new Error('invalid_incident_execution_context');
      return null;
    }
    fields.set(field[1], field[2]);
  }
  return { start: header.index, fields };
}

/** Keep trusted executor evidence before, rather than inside, the control suffix. */
export function insertBeforeLoopContext(prompt, extra = '') {
  const text = asText(prompt);
  if (!extra) return text;
  const context = loopContext(text);
  return context
    ? `${text.slice(0, context.start)}${extra}\n\n${text.slice(context.start)}`
    : `${text}${extra}`;
}

/** 从规范末尾 Para context 取候选，忽略工单正文里同名文本。 */
export function modelCandidatesFromPrompt(prompt) {
  return splitModels(loopContext(prompt)?.fields.get('codex_model_candidates'));
}

export function codexModelCandidates({ env = process.env, prompt = '', reportOnly = false } = {}) {
  const fromPrompt = modelCandidatesFromPrompt(prompt);
  const fromEnv = splitModels(env.DEVFLEET_CODEX_MODEL_CANDIDATES);
  const base = fromPrompt.length ? fromPrompt : fromEnv.length ? fromEnv : [...DEFAULT_CODEX_MODEL_CANDIDATES];
  const review = reportOnly ? splitModels(env.DEVFLEET_CODEX_REVIEW_MODEL) : [];
  return dedupe(fromPrompt.length ? base : [...review, ...base]);
}

export function checkIncidentExecutionBudget(prompt, { reservedChars = 0 } = {}) {
  const raw = loopContext(prompt)?.fields.get('incident_execution_budget');
  if (!raw) return null;
  let requested;
  try {
    const value = JSON.parse(raw);
    if (!value || !['scout', 'fix', 'verify'].includes(value.role)
        || !Number.isSafeInteger(value.context_chars) || value.context_chars < 1
        || !Number.isSafeInteger(value.output_tokens) || value.output_tokens < 1
        || !['low', 'medium', 'high'].includes(value.reasoning_effort)) {
      throw new Error('invalid');
    }
    requested = Object.fromEntries(
      ['role', 'context_chars', 'output_tokens', 'reasoning_effort'].map((key) => [key, value[key]]),
    );
  } catch {
    throw new Error('invalid_incident_execution_budget');
  }
  const actualChars = [...asText(prompt)].length;
  const receipt = {
    requested,
    applied: { context_chars_limit: requested.context_chars },
    context_chars_actual: actualChars,
    context_chars_reserved: reservedChars,
    context_limit_enforced: true,
    output_limit_enforced: false,
  };
  if (actualChars + reservedChars > requested.context_chars) {
    const error = new Error('incident_context_budget_exceeded');
    error.budgetReceipt = { ...receipt, status: 'rejected' };
    throw error;
  }
  return receipt;
}

/** These are real CLI arguments. No unsupported max-output setting is invented. */
export function codexExecutionConfig({ prompt = '', env = process.env, reportOnly = false } = {}) {
  const receipt = checkIncidentExecutionBudget(prompt);
  const requestedEffort = receipt?.requested.reasoning_effort
    || (reportOnly ? asText(env.DEVFLEET_CODEX_REVIEW_EFFORT).trim() : '');
  const effort = ['low', 'medium', 'high'].includes(requestedEffort) ? requestedEffort : '';
  return {
    receipt,
    effort,
    args: ['exec', '--sandbox', 'workspace-write', '--ephemeral',
      ...(effort ? ['-c', `model_reasoning_effort="${effort}"`] : [])],
  };
}

/** Record exact submitted CLI controls on both success and failure, without prompt text. */
export async function runCodexBudgetedAttempt({ execution, model = '', run, log = () => {} }) {
  const args = [...execution.args, ...(model ? ['-m', model] : []), '-'];
  const receipt = {
    ...(execution.receipt || { requested: null, output_limit_enforced: false }),
    application_scope: 'codex_cli_arguments',
    applied: {
      ...execution.receipt?.applied,
      model_cli: model || null,
      reasoning_effort_cli: execution.effort || null,
    },
  };
  const emit = (status) => log(
    `incident_execution_budget_receipt=${JSON.stringify({ ...receipt, status })}`,
    status === 'completed' ? 'info' : 'warn',
  );
  try {
    const output = await run(args);
    emit(asText(output).startsWith('[codex exit=') ? 'failed' : 'completed');
    return output;
  } catch (error) {
    emit('invocation_error');
    throw error;
  }
}

/** 返回鉴权方式与给子进程的 env；不读写任何文件，不输出密钥值。 */
export function resolveCodexAuth(env = process.env) {
  const preferred = asText(env.DEVFLEET_CODEX_API_KEY_ENV).trim() || 'OPENAI_API_KEY';
  const names = dedupe([preferred, 'CODEX_API_KEY']);
  for (const name of names) {
    const value = asText(env[name]).trim();
    if (value) {
      return {
        mode: 'api_key',
        keyEnv: name,
        childEnv: { ...env, CODEX_API_KEY: value },
        label: `auth=api_key(env=${name})`,
      };
    }
  }
  return {
    mode: 'chatgpt_login',
    keyEnv: '',
    childEnv: env,
    label: `auth=chatgpt_login(回退：未找到 ${names.join('/')}，沿用 ChatGPT 登录，受账号模型白名单限制)`,
  };
}

/** 分类模型级错误：'model_unsupported' | 'quota' | ''。 */
export function classifyModelError(text) {
  const raw = asText(text);
  if (!raw) return '';
  if (MODEL_UNAVAILABLE_PATTERNS.some((re) => re.test(raw))) return 'model_unsupported';
  if (QUOTA_PATTERNS.some((re) => re.test(raw))) return 'quota';
  return '';
}

export function formatModelsTried(attempts) {
  return `${CODEX_MODELS_TRIED_MARKER}${attempts.map((a) => `${a.model}:${a.status}`).join(',')}`;
}

/** 进程内可用性表：model -> {status, reason, at}；带 TTL，过期后重新探活。 */
export function createModelAvailability({ ttlMs = 10 * 60_000, now = () => Date.now() } = {}) {
  const table = new Map();
  return {
    get(model) {
      const row = table.get(model);
      if (!row) return null;
      if (now() - row.at > ttlMs) {
        table.delete(model);
        return null;
      }
      return row;
    },
    mark(model, status, reason = '') {
      table.set(model, { status, reason: asText(reason).slice(0, 200), at: now() });
    },
    snapshot() {
      return Object.fromEntries([...table.entries()].map(([k, v]) => [k, v.status]));
    },
  };
}

/**
 * 轻量探活：对状态未知的候选跑一次 runProbe(model)；仅当错误能被判为模型级不可用时标记 unavailable，
 * 网络 / 超时等不确定结果标 unknown（不剔除，避免误杀）。
 */
export async function probeModels({ candidates, availability, runProbe, log = () => {} }) {
  for (const model of candidates) {
    if (availability.get(model)) continue;
    try {
      const result = await runProbe(model);
      const kind = result?.ok ? '' : classifyModelError(result?.output);
      if (result?.ok) availability.mark(model, 'available');
      else if (kind) availability.mark(model, 'unavailable', kind);
      else availability.mark(model, 'unknown', 'probe_inconclusive');
    } catch (err) {
      availability.mark(model, 'unknown', err instanceof Error ? err.message : String(err));
    }
    const row = availability.get(model);
    log(`model probe: ${model} -> ${row?.status || 'unknown'}${row?.reason ? ` (${row.reason})` : ''}`);
  }
  return availability.snapshot();
}

/**
 * 依序尝试候选模型执行同一任务。runAttempt(model) 返回 {ok, output, nonZero}。
 * 只有模型级错误才降级；其余失败立即返回给调用方。
 */
export async function runWithModelFallback({ candidates, availability, runAttempt, log = () => {} }) {
  const attempts = [];
  let last = null;
  for (const model of candidates) {
    const known = availability?.get(model);
    if (known?.status === 'unavailable') {
      attempts.push({ model, status: 'skipped' });
      log(`model skip: ${model} (探活不可用: ${known.reason || 'unavailable'})`);
      continue;
    }
    log(`model attempt: ${model}`);
    const result = await runAttempt(model);
    last = result;
    if (result?.ok) {
      availability?.mark(model, 'available');
      attempts.push({ model, status: 'ok' });
      return { ok: true, model, output: result.output, attempts, exhausted: false };
    }
    const kind = classifyModelError(result?.output);
    if (!kind) {
      attempts.push({ model, status: 'failed' });
      return { ok: false, model, output: result?.output ?? '', attempts, exhausted: false };
    }
    availability?.mark(model, 'unavailable', kind);
    attempts.push({ model, status: kind === 'quota' ? 'quota' : 'unsupported' });
    log(`model downgrade: ${model} -> ${kind}; 换下一个候选`, 'warn');
  }
  const summary = `Codex 候选模型全部不可用 ${formatModelsTried(attempts)}`;
  return {
    ok: false,
    model: '',
    // 保持 `[codex exit=` 前缀，沿用既有非零退出判定与失败摘要（describeCodexFailure 取尾部）。
    output: `${last?.output ? asText(last.output) : '[codex exit=1]'}\n[codex-model-gateway] ${summary}`,
    attempts,
    exhausted: true,
    error: summary,
  };
}
