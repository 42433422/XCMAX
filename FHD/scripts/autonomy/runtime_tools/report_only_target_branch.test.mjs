import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { writeReportOnlyPatch } from './report_only_patch.mjs';

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

test('the report-only patch contains the verified target changes without checkout', async t => {
  const cwd = mkdtempSync(path.join(tmpdir(), 'para-report-target-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
  git('init', '-q');
  git('config', 'user.name', 'Para Test');
  git('config', 'user.email', 'para-test@example.invalid');
  const file = path.join(cwd, 'example.txt');
  writeFileSync(file, 'base line\n');
  git('add', 'example.txt');
  git('commit', '-qm', 'Base');
  const base = git('rev-parse', 'HEAD');
  writeFileSync(file, 'target line\n');
  git('commit', '-qam', 'Target');
  const target = git('rev-parse', 'HEAD');
  git('checkout', '--quiet', '--detach', base);
  mkdirSync(path.join(cwd, '.devfleet'));
  await writeReportOnlyPatch(cwd, { base_sha: base, target_sha: target }, 3000);
  assert.match(readFileSync(path.join(cwd, '.devfleet', 'REPORT_ONLY_DIFF.patch'), 'utf8'), /\+target line/);
  assert.equal(git('rev-parse', 'HEAD'), base);
  assert.equal(readFileSync(file, 'utf8'), 'base line\n');
});
