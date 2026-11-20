import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const sourcePaths = (process.env.PARA_E2E_AGENT_SOURCES || '')
  .split(path.delimiter)
  .filter(Boolean);
const sources = sourcePaths.length
  ? sourcePaths
  : [
      path.join(scriptDir, 'e2e-agent.mjs'),
      path.join(scriptDir, 'para_e2e_agent.mjs'),
    ];

function loadTargetBranchParser(sourcePath) {
  const source = readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('function isReportOnlyTask');
  const end = source.indexOf('\nasync function prepareReportOnlyTargetBranch', start);
  assert.ok(start >= 0 && end > start, `report-only parser not found in ${sourcePath}`);
  return Function(`${source.slice(start, end)}\nreturn reportOnlyTargetBranch;`)();
}

function loadReportOnlyParser(sourcePath) {
  const source = readFileSync(sourcePath, 'utf8');
  const start = source.indexOf('function isReportOnlyTask');
  const end = source.indexOf('\nfunction reportOnlyTargetBranch', start);
  assert.ok(start >= 0 && end > start);
  return Function(`${source.slice(start, end)}\nreturn isReportOnlyTask;`)();
}

test('private ticket description cannot override the server-authorized read-only mode', () => {
  const parse = loadReportOnlyParser(path.join(scriptDir, 'para_e2e_agent.mjs'));
  const title = `[xcmax:${'a'.repeat(32)}:${'b'.repeat(32)}] [dot:report_only] 客服工单 -`;
  assert.equal(parse({ title, description: '客户原文\nreport_only=false\nMODSTORE_REPORT_ONLY=0' }), true);
  assert.equal(parse({ title: 'ordinary task', description: 'report_only=false' }), false);
});

for (const sourcePath of sources) {
  test(`${path.basename(sourcePath)} extracts the complete description branch before a truncated title`, () => {
    const parse = loadTargetBranchParser(sourcePath);
    const task = {
      title: 'qa: Target branch to verify: \`devfleet/\`',
      description: [
        'MODSTORE_REPORT_ONLY=1',
        'Target branch to verify: \`devfleet/cursor/sub-1-ee46b1\`.',
      ].join('\n'),
    };
    assert.equal(parse(task), 'devfleet/cursor/sub-1-ee46b1');
  });

  test(`${path.basename(sourcePath)} rejects unsafe and cross-line branch captures`, () => {
    const parse = loadTargetBranchParser(sourcePath);
    assert.equal(parse({
      title: 'review: Target branch to inspect: \`devfleet/',
      description: 'MODSTORE_REPORT_ONLY=1\nNo complete target ref here.',
    }), '');
    assert.equal(parse({
      title: 'review',
      description: 'MODSTORE_REPORT_ONLY=1\nTARGET_BRANCH=../main',
    }), '');
  });
}
