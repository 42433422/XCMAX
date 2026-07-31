/** Vue / Element Plus plugin bundle for Vite. */

import vue from '@vitejs/plugin-vue'
import VueI18nPlugin from '@intlify/unplugin-vue-i18n/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'
import { fileURLToPath } from 'url'

const viteDir = path.dirname(fileURLToPath(import.meta.url))
const i18nResourceGlob = path.resolve(viteDir, '../src/i18n/locales/**/*.json')

/**
 * @param {object} opts
 * @param {import('vite').PluginOption} opts.staticCopyPlugin
 * @param {string} [opts.xcmaxPublicApiPrefix]
 */
export function createVitePlugins({ staticCopyPlugin, xcmaxPublicApiPrefix = '' }) {
  return [
    vue(),
    VueI18nPlugin({
      include: [i18nResourceGlob],
      runtimeOnly: true,
    }),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
    Components({
      resolvers: [ElementPlusResolver({ importStyle: 'css' })],
      dts: false,
    }),
    staticCopyPlugin,
    {
      name: 'inject-xcmax-api-base',
      transformIndexHtml(html) {
        if (!xcmaxPublicApiPrefix) return html
        const escaped = JSON.stringify(xcmaxPublicApiPrefix)
        const tag = `<script>window.__XCMAX_API_BASE__=${escaped}</script>`
        if (html.includes('__XCMAX_API_BASE__')) return html
        return html.replace('<head>', `<head>\n    ${tag}`)
      },
    },
    {
      name: 'disable-legacy-chat-js',
      transformIndexHtml(html, ctx) {
        if (ctx.server) return html
        return html.replace(
          'window.__ENABLE_LEGACY__ !== false',
          'window.__ENABLE_LEGACY__ === true'
        )
      },
    },
  ]
}
