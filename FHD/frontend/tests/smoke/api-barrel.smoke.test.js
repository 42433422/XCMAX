/**
 * 防止 api/index 与各子模块形成循环依赖（会导致生产包 TDZ 白屏）。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const apiDir = join(process.cwd(), 'src/api');

describe('api barrel smoke', () => {
  it('子模块不得从 ./index 再 import（应使用 ./core）', () => {
    const offenders = [];
    for (const name of readdirSync(apiDir)) {
      if (!name.endsWith('.ts') || name === 'index.ts') continue;
      const text = readFileSync(join(apiDir, name), 'utf8');
      if (/from\s+['"]\.\/index['"]/.test(text)) {
        offenders.push(name);
      }
    }
    expect(offenders, `改用 ./core: ${offenders.join(', ')}`).toEqual([]);
  });
});
