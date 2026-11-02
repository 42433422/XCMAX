import fs from 'node:fs'
import path from 'node:path'

export const redactCredentials = (value, env = process.env) => [env.XCAGI_TEST_PASS, env.XCAGI_TEST_USER].filter(Boolean).reduce((text, secret) => text.replaceAll(secret, '[REDACTED]'), String(value))

export function writeEvidence(file, evidence, env = process.env) {
  fs.writeFileSync(file, JSON.stringify(evidence, (_key, value) => typeof value === 'string' ? redactCredentials(value, env) : value, 2))
}

export function createEvidenceStep({ getPage, evidence, names, dir, env = process.env }) {
  return async function step(id, action) {
    const record = { id, started_at: new Date().toISOString(), input: names, status: 'running' }
    evidence.cases.push(record)
    const page = getPage()
    const capture = file => page.screenshot({ path: path.join(dir, file), fullPage: true, timeout: 60000, mask: [page.locator('#lv-username,#lv-password'), page.getByText(env.XCAGI_TEST_USER || '\0', { exact: true })] })
    try {
      record.actual = await action()
      await capture(`${id}.png`)
      return record.actual
    } catch (error) {
      record.failure_stage = Object.hasOwn(record, 'actual') ? 'screenshot' : 'business'
      record.error = redactCredentials(error.stack || error.message, env)
      if (page) {
        await capture(`${id}-failed.png`).catch(() => {})
        record.visible_buttons = await page.locator('button:visible').evaluateAll(buttons => buttons.map(b => ({ text: b.textContent, label: b.getAttribute('aria-label'), class: b.className, disabled: b.disabled }))).catch(() => [])
        const text = await page.locator('body').innerText().catch(() => '')
        fs.writeFileSync(path.join(dir, `${id}-ui.txt`), redactCredentials(text, env))
      }
      throw error
    } finally { record.status = record.error ? 'failed' : 'passed'; record.finished_at = new Date().toISOString() }
  }
}

export async function visibleVersion(page, expect, expected) {
  let visible
  await expect(async () => {
    // Settings may replace this node while its version request finishes.
    const label = page.locator('.settings-card--about summary .settings-row__meta')
    await label.scrollIntoViewIfNeeded({ timeout: 3000 })
    await expect(label).toHaveText(expected, { timeout: 3000 })
    visible = (await label.innerText({ timeout: 3000 })).trim()
    expect(visible).toBe(expected)
  }).toPass({ timeout: 20000, intervals: [200, 500, 1000] })
  return { expected_version: expected, visible_version: visible }
}
