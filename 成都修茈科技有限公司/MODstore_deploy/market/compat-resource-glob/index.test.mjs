import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import fg from './index.mjs';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

test('Vue discovery preserves sync/async, ignore, dot and literal paths', async () => {
  const cwd = mkdtempSync(join(tmpdir(), 'market-glob-'));
  try {
    for (const name of ['src', '.hidden', 'vendor', 'literal[vue]']) mkdirSync(join(cwd, name));
    for (const name of ['src/App.vue', '.hidden/Hidden.vue', 'vendor/Skip.vue', 'literal[vue]/Exact.vue']) writeFileSync(join(cwd, name), '<template />');
    const options = { cwd, ignore: ['vendor/**'] };
    const expected = ['literal[vue]/Exact.vue', 'src/App.vue'];
    assert.deepEqual(fg.sync('**/*.vue', options).sort(), expected);
    assert.deepEqual((await fg('**/*.vue', options)).sort(), expected);
    assert.equal(fg.sync('**/*.vue', { ...options, dot: true }).length, 3);
    assert.deepEqual(fg.sync('src', options), []);
    assert.deepEqual(fg.sync(fg.convertPathToPattern(join(cwd, 'literal[vue]')) + '/*.vue', { cwd, absolute: true }), [join(cwd, 'literal[vue]/Exact.vue')]);
  } finally { rmSync(cwd, { recursive: true, force: true }); }
});

test('real market Vue/TypeScript ESLint config still loads and checks source', async () => {
  const { ESLint } = await import('eslint');
  const eslint = new ESLint();
  const config = await eslint.calculateConfigForFile('src/Fixture.vue');
  assert.ok(config.plugins.vue && config.plugins['@typescript-eslint']);
  const [result] = await eslint.lintText('<script setup lang="ts">\nconst value: number = 1\n</script>\n<template><span>{{ value }}</span></template>', { filePath: 'src/Fixture.vue' });
  assert.equal(result.fatalErrorCount, 0);
  assert.equal(result.errorCount, 0, JSON.stringify(result.messages));
});

test('deep brace patterns do not exhaust the call stack or hang', () => {
  const source = `import fg from ${JSON.stringify(new URL('./index.mjs', import.meta.url).href)}; fg.sync('{'.repeat(4096) + 'x' + '}'.repeat(4096), { deep: 0 });`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', source], { timeout: 5000, encoding: 'utf8' });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr);
});

test('Vue ESM/CJS configs discover real TS and non-TS files', async () => {
  const variants = [await import('@vue/eslint-config-typescript'), createRequire(import.meta.url)('@vue/eslint-config-typescript')];
  const temp = mkdtempSync(join(tmpdir(), 'market-vue-discovery-'));
  const rootDir = join(temp, 'literal[vue]');
  try {
    mkdirSync(rootDir);
    for (const name of ['src', '.hidden', 'node_modules']) mkdirSync(join(rootDir, name));
    for (const name of ['src/Ts.vue', '.hidden/Hidden.vue', 'node_modules/Skip.vue']) {
      writeFileSync(join(rootDir, name), '<script setup lang="ts">const n = 1</script>');
    }
    writeFileSync(join(rootDir, 'src/Plain.vue'), '<template />');
    for (const vue of variants) {
      vue.configureVueProject({ rootDir, includeDotFolders: false });
      const configs = vue.defineConfigWithVueTs(vue.vueTsConfigs.recommendedTypeChecked);
      const typed = configs.find(config => config.name === '@vue/typescript/default-project-service-for-vue-files');
      const plain = configs.find(config => config.files?.includes('src/Plain.vue'));
      assert.deepEqual(typed?.files, ['src/Ts.vue']);
      assert.deepEqual(plain?.files, ['src/Plain.vue']);
      assert.equal(plain?.languageOptions?.parserOptions?.projectService, false);
    }
  } finally {
    for (const vue of variants) vue.configureVueProject({ rootDir: process.cwd(), includeDotFolders: false });
    rmSync(temp, { recursive: true, force: true });
  }
});
