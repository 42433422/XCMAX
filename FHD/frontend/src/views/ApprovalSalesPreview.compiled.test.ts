import { describe, expect, it } from 'vitest'
import { execFileSync } from 'node:child_process'

// Compile outside jsdom: esbuild requires Node's matching TextEncoder/Uint8Array realm.
const compiledPreview = `
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {transformSync} from 'esbuild';
import {createBuildOptions} from './vite/build.js';
const source=readFileSync('../mods/bridge/xcagi-approval-bridge/frontend/views/approval-workspace/awHelpers.ts','utf8');
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

  it('shows separate order and fulfillment quantities before approval', () => {
    const request = {
      business_type: 'workflow_tool',
      business_data: {
        tool_id: 'sales',
        action: 'execute_closed_loop',
        params: {
          payload: {
            order: {
              customer_name: 'MAC验收0929客户',
              currency: 'CNY',
              items: [
                { product_name: 'MAC验收0929产品13687', quantity: 2, unit_price: 12.5 },
                { product_name: 'MAC验收0929第二商品', quantity: 10, unit_price: 3 },
              ],
            },
            fulfillment: { requested: true, quantity: 4, line_quantities: [1, 3] },
          },
        },
      },
    }
    const output = execFileSync(process.execPath, ['--input-type=module', '-e', compiledPreview, JSON.stringify(request)], {
      encoding: 'utf8',
    })
    const preview = JSON.parse(output)
    expect(preview.customer).toBe('MAC验收0929客户')
    expect(preview.amount).toBe('55.00')
    expect(preview.items.map((item: { quantity: number }) => item.quantity)).toEqual([2, 10])
    expect(preview.deliveryQuantities).toEqual([1, 3])
    expect(preview.receiptAmount).toBeNull()
    expect(preview.operation).toBe('销售闭环')
  })
  it('keeps an explicit receipt amount separate from the order total', () => {
    const request = {
      business_type: 'workflow_tool',
      business_data: {
        tool_id: 'sales',
        action: 'execute_closed_loop',
        params: { payload: {
          order: { items: [{ quantity: 10, unit_price: 100 }], currency: 'CNY' },
          payment_allocation: { requested: true, amount: 375, currency: 'CNY' },
        } },
      },
    }
    const output = execFileSync(process.execPath, ['--input-type=module', '-e', compiledPreview, JSON.stringify(request)], {
      encoding: 'utf8',
    })
    expect(JSON.parse(output)).toMatchObject({ amount: '1000.00', receiptAmount: '375' })
  })

})
