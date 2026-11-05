
import vue from '@vitejs/plugin-vue'
import VueI18n from '@intlify/unplugin-vue-i18n/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

/**
 * @param {object} opts
 * @param {import('vite').PluginOption} opts.staticCopyPlugin
 * @param {string} [opts.xcmaxPublicApiPrefix]
 * @param {string} opts.i18nInclude
 */
export function createVitePlugins({ staticCopyPlugin, xcmaxPublicApiPrefix = '', i18nInclude }) {
  return [
    vue(),
    VueI18n({
      runtimeOnly: true,
      compositionOnly: true,
      jitCompilation: false,
      dropMessageCompiler: true,
      include: i18nInclude,
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
        if (!xcmaxPublicApiPrefix || html.includes('__XCMAX_API_BASE__')) return html
        return html.replace('<head>', `<head>\n    <script>window.__XCMAX_API_BASE__=${JSON.stringify(xcmaxPublicApiPrefix)}</script>`)
      },
    },
    {
      name: 'disable-legacy-chat-js',
      transformIndexHtml(html, ctx) {
        return ctx.server ? html : html.replace('window.__ENABLE_LEGACY__ !== false', 'window.__ENABLE_LEGACY__ === true')
      },
    },
  ]
}
