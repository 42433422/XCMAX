import { test, expect } from '@playwright/test'
import { installStartupReadinessMocks } from '../e2e/startup-readiness-fixture'
import { capture, isolate } from './capture'

test.use({ deviceScaleFactor: 2 })

for (const colorScheme of ['light', 'dark'] as const) {
  for (const [width, height] of [[1024, 768], [768, 1024]]) {
    test('desktop a11y keyboard ' + colorScheme + '-' + width, async ({ page, baseURL }) => {
      await page.setViewportSize({ width, height })
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
      await isolate(page, baseURL!)
      await installStartupReadinessMocks(page)
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 30000 })
      const composer = page.locator('#messageInput')
      await expect(composer).toBeVisible()
      await composer.fill('请核对订单差异')
      await composer.focus()
      await expect(composer).toBeFocused()
      // Check the keyboard focus indicator, not merely the active element.
      await composer.evaluate(element => (element as HTMLElement).blur())
      const unfocused = await composer.evaluate(element => {
        const style = getComputedStyle(element)
        return style.outline + '|' + style.boxShadow
      })
      await composer.focus()
      const focused = await composer.evaluate(element => {
        const style = getComputedStyle(element)
        return style.outline + '|' + style.boxShadow
      })
      expect(focused, 'focused input must visibly differ from its idle state').not.toBe(unfocused)
      await capture(page, 'a11y-composer-focused-' + colorScheme + '-' + width, 'device')
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => !!document.activeElement && document.activeElement !== document.body)).toBe(true)
      expect(await page.evaluate(() => document.activeElement?.matches(':focus-visible'))).toBe(true)
      await capture(page, 'a11y-composer-tab-' + colorScheme + '-' + width, 'device')
    })
  }
}
