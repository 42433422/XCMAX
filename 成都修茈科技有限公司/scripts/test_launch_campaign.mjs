import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const source = readFileSync(new URL('../main.js', import.meta.url), 'utf8')
const start = source.indexOf('function launchCampaignWindow(')
const end = source.indexOf("document.addEventListener('DOMContentLoaded', async", start)
assert.ok(start >= 0 && end > start)
const countdown = runInNewContext(source.slice(start, end) + '\nlaunchCampaignWindow')
const begin = Date.parse('2026-12-01T00:00:00Z')
const finish = Date.parse('2026-12-31T00:00:00Z')
const campaign = { enabled: true, starts_at: '2026-12-01T00:00:00Z', ends_at: '2026-12-31T00:00:00Z', benefits: ['test benefit'] }

test('fixed dates, active interval and no reset on reload', () => {
  assert.equal(countdown(campaign, begin - 1), null)
  assert.equal(countdown(campaign, begin), '30 天 : 00 时 : 00 分 : 00 秒')
  assert.equal(countdown(campaign, finish - 1000), '0 天 : 00 时 : 00 分 : 01 秒')
  assert.equal(countdown(campaign, finish), null)
  assert.equal(countdown(campaign, finish + 86400000), null)
})
test('disabled, missing and invalid campaign data fail closed', () => {
  for (const value of [null, {}, {...campaign, enabled: false}, {...campaign, benefits: []}, {...campaign, ends_at: null}, {...campaign, starts_at: '2026-12-01T00:00:00'}, {...campaign, starts_at: campaign.ends_at}]) {
    assert.equal(countdown(value, begin), null)
  }
})
