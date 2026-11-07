
import vue from '@vitejs/plugin-vue'
import VueI18n from '@intlify/unplugin-vue-i18n/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { routerDevtoolsNullGuard } from './routerDevtoolsGuard.js'

/**
 * @param {object} opts
 * @param {string} [opts.xcmaxPublicApiPrefix]
 * @param {string} opts.i18nInclude
 */
export function createVitePlugins({ xcmaxPublicApiPrefix = '', i18nInclude }) {
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
    routerDevtoolsNullGuard(),
    {
      name: 'inject-xcmax-api-base',
      transformIndexHtml(html) {
        if (!xcmaxPublicApiPrefix) return html
        const activeHtml = html.replace(/<!--[\s\S]*?-->/g, '')
        if (activeHtml.includes('__XCMAX_API_BASE__')) return html
        const serializedPrefix = JSON.stringify(xcmaxPublicApiPrefix).replaceAll('<', '\\u003c')
        return html.replace('<head>', () => `<head>\n    <script>window.__XCMAX_API_BASE__=${serializedPrefix}</script>`)
      },
    },
  ]
}
