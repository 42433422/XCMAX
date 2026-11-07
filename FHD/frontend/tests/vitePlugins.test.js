import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'
import { createVitePlugins } from '../vite/plugins.js'

// Build-only plugins load esbuild, whose typed arrays cannot cross the jsdom realm.
vi.mock('@vitejs/plugin-vue', () => ({ default: () => ({}) }))
vi.mock('@intlify/unplugin-vue-i18n/vite', () => ({ default: () => ({}) }))
vi.mock('unplugin-auto-import/vite', () => ({ default: () => ({}) }))
vi.mock('unplugin-vue-components/vite', () => ({ default: () => ({}) }))
vi.mock('unplugin-vue-components/resolvers', () => ({ ElementPlusResolver: () => ({}) }))

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const indexHtml = readFileSync(path.join(frontendDir, 'index.html'), 'utf8')

function transformHtml(prefix, html = indexHtml) {
  const plugin = createVitePlugins({
    xcmaxPublicApiPrefix: prefix,
    i18nInclude: path.join(frontendDir, 'src/i18n/locales/**/*.json'),
  }).find((entry) => entry.name === 'inject-xcmax-api-base')
  return plugin.transformIndexHtml(html)
}

describe('public API base injection', () => {
  it('injects into the real index despite its commented configuration example', () => {
    const result = transformHtml('/fhd-api')
    const document = new DOMParser().parseFromString(result, 'text/html')
    const scripts = Array.from(document.scripts).map((script) => script.textContent)
    expect(scripts).toContain('window.__XCMAX_API_BASE__="/fhd-api"')
  })

  it('preserves an existing active configuration', () => {
    const configured = indexHtml.replace('<head>', '<head><script>window.__XCMAX_API_BASE__="/custom-api"</script>')
    expect(transformHtml('/fhd-api', configured)).toBe(configured)
  })

  it.each(['</script\t\n bar>', '</script ignored=">">'])('recognizes an active script closed by %s', (endTag) => {
    const configured = `<html><head><script>window.__XCMAX_API_BASE__="/custom-api"${endTag}</head><body></body></html>`
    const document = new DOMParser().parseFromString(configured, 'text/html')
    expect(document.scripts[0].textContent).toBe('window.__XCMAX_API_BASE__="/custom-api"')
    expect(transformHtml('/fhd-api', configured)).toBe(configured)
  })

  it('does not treat inert template scripts as active configuration', () => {
    const template = '<template><script>window.__XCMAX_API_BASE__="/template-only"</script></template>'
    const result = transformHtml('/fhd-api', `<html><head>${template}</head><body></body></html>`)
    const document = new DOMParser().parseFromString(result, 'text/html')
    expect(Array.from(document.scripts).map((script) => script.textContent)).toEqual([
      'window.__XCMAX_API_BASE__="/fhd-api"',
    ])
    expect(result).toContain(template)
  })

  it('leaves the index unchanged when no prefix is configured', () => {
    expect(transformHtml('')).toBe(indexHtml)
  })

  it('does not inject twice when the transform is repeated', () => {
    const first = transformHtml('/fhd-api')
    expect(transformHtml('/fhd-api', first)).toBe(first)
  })

  it.each(['/api/$&', '/api/</script>tail'])('preserves the API prefix %s after HTML parsing', (prefix) => {
    const result = transformHtml(prefix)
    const document = new DOMParser().parseFromString(result, 'text/html')
    const context = { window: {} }
    runInNewContext(document.scripts[0].textContent, context)
    expect(context.window.__XCMAX_API_BASE__).toBe(prefix)
    expect(transformHtml(prefix, result)).toBe(result)
  })
})
