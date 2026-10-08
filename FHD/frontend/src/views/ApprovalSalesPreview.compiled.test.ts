import { describe, expect, it } from 'vitest'
import { execFileSync } from 'node:child_process'

// Compile outside jsdom: esbuild requires Node's matching TextEncoder/Uint8Array realm.
const compiledPreview = `
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {transformSync} from 'esbuild';
import {createBuildOptions} from './vite/build.js';
const source=readFileSync('../mods/xcagi-approval-bridge/frontend/views/approval-workspace/awHelpers.ts','utf8');
const {code}=transformSync(source,{loader:'ts',format:'cjs',target:createBuildOptions().target});
const module={exports:{}};
runInNewContext(code,{module,exports:module.exports});
console.log(JSON.stringify(module.exports.salesApprovalPreview(JSON.parse(process.argv[1]))));
`

describe('sales approval totals in production JavaScript', () => {
  it.each([
    [[{ quantity: 2, unit_price: 12.5 }], '25.00'],
    [[{ quantity: 3, unit_price: '0.1' }, { quantity: 1, unit_price: '0.2' }], '0.50'],
  ])('executes exact totals after the real production target transform', (items, amount) => {
    const request = { business_type: 'workflow_tool', business_data: { tool_id: 'sales', action: 'create_order', params: { items } } }
    const output = execFileSync(process.execPath, ['--input-type=module', '-e', compiledPreview, JSON.stringify(request)], {
      encoding: 'utf8',
    })
    expect(JSON.parse(output).amount).toBe(amount)
  })
})
