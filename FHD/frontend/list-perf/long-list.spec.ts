import { expect, test, type Page } from '@playwright/test'
import { writeFileSync } from 'node:fs'

type Bench = {
  load(count: number): Promise<number>
  clear(): Promise<void>
  count(): number
  selectedCount(): number
}
declare global { interface Window { __xcmaxListBench: Bench } }

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

test('1k/10k business rows: DOM, mount latency and Chromium heap trajectory', async ({ page, context }, info) => {
  const strict = process.env.LIST_PERF_ASSERT_BOUNDED === '1'
  const points: Record<string, unknown>[] = []
  const errors: string[] = []
  page.on('pageerror', error => { if (errors.length < 20) errors.push(error.message) })
  await page.goto('/list-perf/index.html', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('#list-perf-fixture')).toBeVisible({ timeout: 30000 })
  const session = await context.newCDPSession(page)
  await session.send('Performance.enable')
  await session.send('HeapProfiler.enable')

  async function snapshot(label: string, mountMs: number | null = null) {
    await paint(page)
    await session.send('HeapProfiler.collectGarbage')
    const heap = await session.send('Runtime.getHeapUsage')
    const perf = await session.send('Performance.getMetrics')
    const metrics = Object.fromEntries(perf.metrics.map(m => [m.name, m.value]))
    const dom = await page.evaluate(() => ({
      total_nodes: document.querySelectorAll('*').length,
      mounted_business_rows: document.querySelectorAll('tbody tr[data-row-id]').length,
      loaded_label: document.querySelector('#record-count')?.textContent ?? '',
    }))
    points.push({
      label, at_ms: Date.now(), mount_ms: mountMs, ...dom,
      chromium_heap_used_bytes: heap.usedSize,
      chromium_heap_allocated_bytes: heap.totalSize,
      js_heap_used_bytes: metrics.JSHeapUsedSize ?? null,
      nodes_metric: metrics.Nodes ?? null,
      documents_metric: metrics.Documents ?? null,
    })
    return dom.mounted_business_rows
  }

  try {
    await snapshot('empty')
    for (const count of [1000, 10000]) {
      const elapsed = await page.evaluate(async n => window.__xcmaxListBench.load(n), count)
      const mounted = await snapshot('loaded-' + count, elapsed)
      expect(await page.evaluate(() => window.__xcmaxListBench.count())).toBe(count)
      expect(mounted).toBeGreaterThan(0)
      if (strict) expect(mounted, 'candidate must not mount all data rows').toBeLessThanOrEqual(100)
      const pager = page.locator('.data-table-pages button:last-child')
      if (await pager.count()) {
        await pager.click()
        await snapshot('page-2-' + count)
        if (strict) {
          expect(await page.locator('tbody tr[data-row-id]').count()).toBeLessThanOrEqual(100)
          expect(await page.locator('tbody tr[data-row-id]').first().getAttribute('data-row-id')).toBe('101')
        }
      }
      await page.evaluate(() => window.__xcmaxListBench.clear())
      await snapshot('cleared-' + count)
    }
    // Synthetic short soak, not an 8-hour device run.
    for (let i = 1; i <= 30; i++) {
      const elapsed = await page.evaluate(() => window.__xcmaxListBench.load(1000))
      if (i % 5 === 0) await snapshot('soak-loaded-' + i, elapsed)
      await page.evaluate(() => window.__xcmaxListBench.clear())
      if (i % 5 === 0) await snapshot('soak-cleared-' + i)
    }
    if (strict) {
      expect(await page.locator('tbody tr[data-row-id]').count()).toBe(0)
      expect(errors, 'candidate page errors').toEqual([])
    }
  } finally {
    writeFileSync(info.outputPath('memory-curve.json'), JSON.stringify({
      evidence_type: 'measured',
      source_sha: process.env.SOURCE_SHA || '',
      baseline_or_candidate: strict ? 'candidate' : 'baseline',
      scope: 'synthetic real Vue DataTable in Chromium on CI; not native Electron/Flutter or production ERP network',
      runner: { node: process.version, browser: 'chromium', viewport: { width: 1440, height: 900 } },
      point_count: points.length, points, page_errors: errors,
    }, null, 2))
    await session.detach()
  }
})
