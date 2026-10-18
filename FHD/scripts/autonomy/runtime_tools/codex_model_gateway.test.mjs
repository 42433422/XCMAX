import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_CODEX_MODEL_CANDIDATES,
  classifyModelError,
  codexModelCandidates,
  createModelAvailability,
  modelCandidatesFromPrompt,
  probeModels,
  resolveCodexAuth,
  runWithModelFallback,
} from './codex_model_gateway.mjs';
import { describeCodexFailure } from './trae_failover.mjs';

const UNSUPPORTED = "[codex exit=1]\nERROR: {\"detail\":\"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.\"} (HTTP 400)";

test('默认候选顺序 sol > terra > luna，可由 env 和派单提示覆盖', () => {
  assert.deepEqual(DEFAULT_CODEX_MODEL_CANDIDATES, ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']);
  assert.deepEqual(codexModelCandidates({ env: {} }), ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna']);
  assert.deepEqual(
    codexModelCandidates({ env: { DEVFLEET_CODEX_MODEL_CANDIDATES: 'a, b' } }),
    ['a', 'b'],
  );
  const prompt = 'fix it\nMODstore loop context:\n- codex_model_candidates: x>y,x\n';
  assert.deepEqual(modelCandidatesFromPrompt(prompt), ['x', 'y', 'x']);
  assert.deepEqual(codexModelCandidates({ env: { DEVFLEET_CODEX_MODEL_CANDIDATES: 'a' }, prompt }), ['x', 'y']);
  assert.deepEqual(
    codexModelCandidates({ env: { DEVFLEET_CODEX_REVIEW_MODEL: 'fast' }, reportOnly: true }),
    ['fast', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
  );
});

test('API Key 只注入子进程 CODEX_API_KEY，缺 key 时标注回退 ChatGPT 登录且不泄露值', () => {
  const secret = 'sk-test-not-a-real-key-000000';
  const auth = resolveCodexAuth({ OPENAI_API_KEY: secret, PATH: '/bin' });
  assert.equal(auth.mode, 'api_key');
  assert.equal(auth.keyEnv, 'OPENAI_API_KEY');
  assert.equal(auth.childEnv.CODEX_API_KEY, secret);
  assert.doesNotMatch(auth.label, /sk-test/);

  const custom = resolveCodexAuth({ DEVFLEET_CODEX_API_KEY_ENV: 'XC_CODEX_KEY', XC_CODEX_KEY: secret });
  assert.equal(custom.keyEnv, 'XC_CODEX_KEY');

  const login = resolveCodexAuth({ PATH: '/bin' });
  assert.equal(login.mode, 'chatgpt_login');
  assert.equal(login.childEnv.CODEX_API_KEY, undefined);
  assert.match(login.label, /chatgpt_login\(回退/);
});

test('模型错误分类：400 不支持 / 不存在 / 额度；普通失败不算', () => {
  assert.equal(classifyModelError(UNSUPPORTED), 'model_unsupported');
  assert.equal(classifyModelError('Error: model_not_found'), 'model_unsupported');
  assert.equal(classifyModelError('The model `gpt-5.6-luna` does not exist'), 'model_unsupported');
  assert.equal(classifyModelError("You've hit your usage limit."), 'quota');
  assert.equal(classifyModelError('insufficient_quota'), 'quota');
  assert.equal(classifyModelError('[codex exit=1]\npatch failed to apply'), '');
  assert.equal(classifyModelError(''), '');
});

test('400 自动降级到下一个模型，同一任务续跑成功', async () => {
  const calls = [];
  const availability = createModelAvailability();
  const result = await runWithModelFallback({
    candidates: ['gpt-6.1-sol', 'gpt-5.6-terra'],
    availability,
    runAttempt: async (model) => {
      calls.push(model);
      return model === 'gpt-6.1-sol' ? { ok: false, output: UNSUPPORTED } : { ok: true, output: 'done' };
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.model, 'gpt-5.6-terra');
  assert.equal(result.output, 'done');
  assert.deepEqual(calls, ['gpt-6.1-sol', 'gpt-5.6-terra']);
  assert.deepEqual(result.attempts, [
    { model: 'gpt-6.1-sol', status: 'unsupported' },
    { model: 'gpt-5.6-terra', status: 'ok' },
  ]);
  assert.equal(availability.get('gpt-6.1-sol').status, 'unavailable');
});

test('候选全部失败：明确错误并附尝试过的模型列表', async () => {
  const result = await runWithModelFallback({
    candidates: ['a', 'b'],
    availability: createModelAvailability(),
    runAttempt: async (model) => ({
      ok: false,
      output: model === 'a' ? UNSUPPORTED : '[codex exit=1]\ninsufficient_quota',
    }),
  });
  assert.equal(result.ok, false);
  assert.equal(result.exhausted, true);
  assert.match(result.error, /候选模型全部不可用 codex_models_tried=a:unsupported,b:quota/);
  assert.ok(result.output.startsWith('[codex exit='));
  assert.match(describeCodexFailure(result.output).summary, /codex_models_tried=a:unsupported,b:quota/);
});

test('非模型类失败不降级（交给既有执行器回退 / 超时逻辑）', async () => {
  const calls = [];
  const result = await runWithModelFallback({
    candidates: ['a', 'b'],
    availability: createModelAvailability(),
    runAttempt: async (model) => {
      calls.push(model);
      return { ok: false, output: '[codex exit=1]\nsandbox denied write' };
    },
  });
  assert.deepEqual(calls, ['a']);
  assert.equal(result.exhausted, false);
  assert.deepEqual(result.attempts, [{ model: 'a', status: 'failed' }]);
});

test('探活：不可用模型被标记并在派单时跳过；不确定结果不剔除', async () => {
  const availability = createModelAvailability();
  const probed = [];
  const snapshot = await probeModels({
    candidates: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
    availability,
    runProbe: async (model) => {
      probed.push(model);
      if (model === 'gpt-5.6-sol') return { ok: false, output: UNSUPPORTED };
      if (model === 'gpt-5.6-luna') throw new Error('network down');
      return { ok: true, output: 'OK' };
    },
  });
  assert.deepEqual(snapshot, { 'gpt-5.6-sol': 'unavailable', 'gpt-5.6-terra': 'available', 'gpt-5.6-luna': 'unknown' });

  // 缓存命中：再次探活不重复调用
  await probeModels({ candidates: ['gpt-5.6-sol'], availability, runProbe: async () => assert.fail('cached') });
  assert.equal(probed.length, 3);

  const calls = [];
  const result = await runWithModelFallback({
    candidates: ['gpt-5.6-sol', 'gpt-5.6-terra'],
    availability,
    runAttempt: async (model) => {
      calls.push(model);
      return { ok: true, output: 'fixed' };
    },
  });
  assert.deepEqual(calls, ['gpt-5.6-terra']);
  assert.deepEqual(result.attempts, [
    { model: 'gpt-5.6-sol', status: 'skipped' },
    { model: 'gpt-5.6-terra', status: 'ok' },
  ]);
});

test('探活缓存过期后重新探活', async () => {
  let clock = 0;
  const availability = createModelAvailability({ ttlMs: 100, now: () => clock });
  availability.mark('m', 'unavailable', 'model_unsupported');
  assert.equal(availability.get('m').status, 'unavailable');
  clock = 500;
  assert.equal(availability.get('m'), null);
});
