
import vue from '@vitejs/plugin-vue'
import VueI18n from '@intlify/unplugin-vue-i18n/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { parse } from 'parse5'
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
        const nodes = [parse(html)]
        while (nodes.length) {
          const node = nodes.pop()
          if (node.nodeName === 'script' && node.childNodes.some((child) =>
            child.nodeName === '#text' && child.value.includes('__XCMAX_API_BASE__'))) return html
          // Follow active child nodes, not the inert template.content fragment.
          nodes.push(...(node.childNodes || []))
        }
        const serializedPrefix = JSON.stringify(xcmaxPublicApiPrefix).replaceAll('<', '\\u003c')
        return html.replace('<head>', () => `<head>\n    <script>window.__XCMAX_API_BASE__=${serializedPrefix}</script>`)
      },
    },
  ]
}
