import assert from 'node:assert/strict';
import test from 'node:test';

import {
  describeCodexFailure,
  describeTraeFailure,
  formatCodexNonZeroOutput,
  isCodexProviderFailoverEligible,
  isTraeProviderFailoverEligible,
  parseTraeStream,
} from './trae_failover.mjs';

test('parses the final structured Trae result', () => {
  const parsed = parseTraeStream([
    '{"type":"system","subtype":"init"}',
    '{"type":"result","subtype":"error_during_execution","error":"quota exceeded"}',
  ].join('\n'));

  assert.equal(parsed.error, 'quota exceeded');
  assert.equal(parsed.subtype, 'error_during_execution');
});

test('quota and transient provider failures are eligible for Codex failover', () => {
  const details = describeTraeFailure({
    code: 1,
    stdout: '{"type":"result","subtype":"error_during_execution","error":"failed to call agent: Model usage has reached personal quota limit."}\n',
    stderr: '',
    message: 'Command failed with a prompt that must never be echoed',
  });

  assert.equal(isTraeProviderFailoverEligible(details), true);
  assert.match(details.summary, /personal quota limit/);
  assert.doesNotMatch(details.summary, /must never be echoed/);
  assert.equal(isTraeProviderFailoverEligible('HTTP 429 too many requests'), true);
  assert.equal(isTraeProviderFailoverEligible('503 service unavailable'), true);
});

test('policy failures and unknown command failures do not silently change tools', () => {
  assert.equal(isTraeProviderFailoverEligible('safety policy violation'), false);
  assert.equal(isTraeProviderFailoverEligible('permission denied'), false);
  assert.equal(isTraeProviderFailoverEligible('syntax error in local wrapper'), false);
});

test('Codex non-zero diagnostics preserve the provider error tail instead of the prompt head', () => {
  const output = formatCodexNonZeroOutput({
    code: 1,
    stdout: '',
    stderr: `user\n${'large prompt '.repeat(1000)}\nERROR: You've hit your usage limit. Try again later.`,
  }, 600);

  assert.ok(output.length <= 600);
  assert.match(output, /^\[codex exit=1\]/);
  assert.match(output, /diagnostic tail/);
  assert.match(output, /usage limit/);
  assert.doesNotMatch(output, /^\[codex exit=1\]\nuser/);
});

test('Codex capacity failures can fail over to Trae while policy failures cannot', () => {
  const details = describeCodexFailure([
    '[codex exit=1]',
    'stream disconnected - retrying',
    "ERROR: You've hit your usage limit. Try again later.",
  ].join('\n'));

  assert.equal(isCodexProviderFailoverEligible(details), true);
  assert.match(details.summary, /usage limit/);
  assert.equal(isCodexProviderFailoverEligible('[codex exit=1]\nsafety policy violation'), false);
  assert.equal(isCodexProviderFailoverEligible('[codex exit=1]\ninvalid local argument'), false);
});
