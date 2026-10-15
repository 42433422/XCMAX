import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { sourceIdentity } from './control_git_handoff.mjs';

test('two independent checkouts bind the same commit and source archive; mismatches fail', async () => {
  const root = mkdtempSync(join(tmpdir(), 'control-handoff-test-'));
  const git = (args, cwd = root) => execFileSync('git', args, { cwd, stdio: ['ignore', 'pipe', 'pipe'] }).toString().trim();
  try {
    git(['init', '-b', 'main']);
    writeFileSync(join(root, 'fixture.txt'), 'source fixture\n');
    git(['add', 'fixture.txt']);
    git(['-c', 'user.name=Fixture', '-c', 'user.email=fixture@test.local', 'commit', '-m', 'fixture']);
    const expected = await sourceIdentity(root);
    const copy = root + '-copy';
    git(['clone', root, copy]);
    try {
      assert.deepEqual(await sourceIdentity(copy, expected.commit_sha, expected.archive_sha256), expected);
      await assert.rejects(sourceIdentity(copy, '0'.repeat(40)), /commit_mismatch/);
      await assert.rejects(sourceIdentity(copy, expected.commit_sha, '0'.repeat(64)), /archive_mismatch/);
      writeFileSync(join(copy, 'fixture.txt'), 'modified');
      await assert.rejects(sourceIdentity(copy), /workspace_not_clean/);
    } finally { rmSync(copy, { recursive: true, force: true }); }
  } finally { rmSync(root, { recursive: true, force: true }); }
});
