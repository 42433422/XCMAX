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
 * - DEVFLEET_CODEX_MODEL_GATEWAY=0 关闭网关，恢复旧行为（不传 -m）。
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

/** 从 Para 派发提示里取 `codex_model_candidates: a,b,c`（派发侧可按工单下发）。 */
export function modelCandidatesFromPrompt(prompt) {
  const match = asText(prompt).match(/^\s*-?\s*codex_model_candidates\s*[:=]\s*(.+)$/im);
  return match ? splitModels(match[1]) : [];
}

export function codexModelCandidates({ env = process.env, prompt = '', reportOnly = false } = {}) {
  const fromPrompt = modelCandidatesFromPrompt(prompt);
  const fromEnv = splitModels(env.DEVFLEET_CODEX_MODEL_CANDIDATES);
  const base = fromPrompt.length ? fromPrompt : fromEnv.length ? fromEnv : [...DEFAULT_CODEX_MODEL_CANDIDATES];
  const review = reportOnly ? splitModels(env.DEVFLEET_CODEX_REVIEW_MODEL) : [];
  return dedupe([...review, ...base]);
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
