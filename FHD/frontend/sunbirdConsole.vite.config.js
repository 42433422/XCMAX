/**
 * 太阳鸟企业壳独立 Vite 配置：base=/sunbird/，产物 templates/sunbird-vue-dist。
 */
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const hostRoot = __dirname
const sunbirdRoot = path.resolve(hostRoot, '../sunbird-console')
const sunbirdSrc = path.join(sunbirdRoot, 'src')
const hostSrc = path.join(hostRoot, 'src')
const hostConstants = path.join(hostSrc, 'constants')

const API_BASE = process.env.VITE_API_BASE || 'http://127.0.0.1:5000'
const devPort = Number(process.env.VITE_DEV_PORT || 5012)

function modViewsDir(modId) {
  const rel = path.join(modId, 'frontend', 'views')
  for (const base of [path.resolve(hostRoot, '../mods'), path.resolve(hostRoot, '../XCAGI/mods')]) {
    const p = path.join(base, rel)
    if (fs.existsSync(p)) return p
  }
  return path.join(hostRoot, '../mods', rel)
}

const adminSrc = path.join(sunbirdRoot, '../admin-console/src')

const sunbirdModuleAliases = [
  'constants/accountModBinding.ts',
  'constants/genericModPack.ts',
  'constants/erpDomainMod.ts',
  'constants/personnelModApi.ts',
  'constants/protectedMods.ts',
  'utils/erpDomainPaths.ts',
  'utils/modPrimaryWorkflow.ts',
  'composables/useServiceBridgeInstance.ts',
].flatMap((sub) => {
  const full = path.join(sunbirdSrc, sub)
  const base = sub.replace(/\.(ts|vue)$/, '')
  return [
    { find: `@/${sub}`, replacement: full },
    { find: `@/${base}`, replacement: full },
  ]
})

function buildDevProxy(apiBase) {
  return {
    '/api': { target: apiBase, changeOrigin: true },
    '/health': { target: apiBase, changeOrigin: true },
    '/xcmax-dashboard': { target: apiBase, changeOrigin: true },
  }
}

export default defineConfig(() => ({
  root: sunbirdRoot,
  plugins: [
    vue(),
    AutoImport({ resolvers: [ElementPlusResolver()], dts: false }),
    Components({ resolvers: [ElementPlusResolver({ importStyle: 'css' })], dts: false }),
  ],
  define: {
    'import.meta.env.VITE_XCMAX_SUNBIRD_CONSOLE': JSON.stringify('1'),
    'import.meta.env.VITE_XCMAX_ADMIN_CONSOLE': JSON.stringify(''),
  },
  base: '/sunbird/',
  resolve: {
    alias: [
      ...sunbirdModuleAliases,
      {
        find: '@/components/contract/ContractEsignPanel.vue',
        replacement: path.join(adminSrc, 'components/contract/ContractEsignPanel.vue'),
      },
      {
        find: '@/api/contractLifecycle',
        replacement: path.join(adminSrc, 'api/contractLifecycle.ts'),
      },
      {
        find: '@/api/contractLifecycle.ts',
        replacement: path.join(adminSrc, 'api/contractLifecycle.ts'),
      },
      {
        find: '@/api/financeLedger',
        replacement: path.join(adminSrc, 'api/financeLedger.ts'),
      },
      {
        find: '@/api/financeLedger.ts',
        replacement: path.join(adminSrc, 'api/financeLedger.ts'),
      },
      {
        find: '@/api/wechatGroupBridge',
        replacement: path.join(adminSrc, 'api/wechatGroupBridge.ts'),
      },
      {
        find: '@/api/wechatGroupBridge.ts',
        replacement: path.join(adminSrc, 'api/wechatGroupBridge.ts'),
      },
      {
        find: '@/composables/useWechatEnterpriseBinding',
        replacement: path.join(adminSrc, 'composables/useWechatEnterpriseBinding.ts'),
      },
      {
        find: '@/composables/useWechatEnterpriseBinding.ts',
        replacement: path.join(adminSrc, 'composables/useWechatEnterpriseBinding.ts'),
      },
      {
        find: '@/composables/useWechatGroupBridge',
        replacement: path.join(adminSrc, 'composables/useWechatGroupBridge.ts'),
      },
      {
        find: '@/composables/useWechatGroupBridge.ts',
        replacement: path.join(adminSrc, 'composables/useWechatGroupBridge.ts'),
      },
      {
        find: '@/constants/hostViewGlob',
        replacement: path.join(hostConstants, 'hostViewGlob.full.ts'),
      },
      {
        find: '@/constants/modPhysicalViewGlob',
        replacement: path.join(hostConstants, 'modPhysicalViewGlob.full.ts'),
      },
      {
        find: '@/constants/modRouteGlob',
        replacement: path.join(hostConstants, 'modRouteGlob.full.ts'),
      },
      { find: '@host', replacement: hostSrc },
      { find: '@', replacement: hostSrc },
      { find: '@amin', replacement: path.resolve(hostRoot, '../AMIN') },
      {
        find: '@mod-views/taiyangniao-pro',
        replacement: modViewsDir('taiyangniao-pro'),
      },
      {
        find: '@mod-views/xcagi-lan-license-bridge',
        replacement: modViewsDir('xcagi-lan-license-bridge'),
      },
      {
        find: '@mod-views/xcagi-customer-service-bridge',
        replacement: modViewsDir('xcagi-customer-service-bridge'),
      },
      {
        find: '@mod-views/xcagi-approval-bridge',
        replacement: modViewsDir('xcagi-approval-bridge'),
      },
      {
        find: '@mod-views/xcagi-planner-bridge',
        replacement: modViewsDir('xcagi-planner-bridge'),
      },
      {
        find: '@mod-views/xcagi-model-payment-bridge',
        replacement: modViewsDir('xcagi-model-payment-bridge'),
      },
      {
        find: '@mod-views/xcagi-erp-domain-bridge',
        replacement: modViewsDir('xcagi-erp-domain-bridge'),
      },
      {
        find: '@mod-views/xcagi-office-employee-pack-bridge',
        replacement: modViewsDir('xcagi-office-employee-pack-bridge'),
      },
      {
        find: '@mod-views/xcagi-workflow-visualization-bridge',
        replacement: modViewsDir('xcagi-workflow-visualization-bridge'),
      },
      {
        find: '@mod-views/xcagi-core-workflow-employees',
        replacement: modViewsDir('xcagi-workflow-visualization-bridge'),
      },
      { find: 'vue', replacement: path.join(hostRoot, 'node_modules/vue') },
      { find: 'xlsx', replacement: path.join(hostRoot, 'node_modules/xlsx') },
      {
        find: '@vue-flow/core',
        replacement: path.join(hostRoot, 'node_modules/@vue-flow/core'),
      },
      {
        find: '@vue-flow/background',
        replacement: path.join(hostRoot, 'node_modules/@vue-flow/background'),
      },
      {
        find: '@vue-flow/controls',
        replacement: path.join(hostRoot, 'node_modules/@vue-flow/controls'),
      },
      {
        find: '@vue-flow/minimap',
        replacement: path.join(hostRoot, 'node_modules/@vue-flow/minimap'),
      },
      {
        find: '@dagrejs/dagre',
        replacement: path.join(hostRoot, 'node_modules/@dagrejs/dagre'),
      },
      { find: 'mermaid', replacement: path.join(hostRoot, 'node_modules/mermaid') },
      { find: 'vue-router', replacement: path.join(hostRoot, 'node_modules/vue-router') },
      { find: 'pinia', replacement: path.join(hostRoot, 'node_modules/pinia') },
      { find: 'element-plus', replacement: path.join(hostRoot, 'node_modules/element-plus') },
    ],
    dedupe: ['vue', 'vue-router', 'pinia', 'element-plus', 'xlsx'],
  },
  server: {
    host: '0.0.0.0',
    port: devPort,
    proxy: buildDevProxy(API_BASE),
    fs: { allow: [sunbirdRoot, hostRoot, path.resolve(hostRoot, '..')] },
  },
  preview: {
    host: '0.0.0.0',
    port: devPort,
    proxy: buildDevProxy(API_BASE),
  },
  publicDir: path.join(hostRoot, 'public'),
  worker: { format: 'es' },
  build: {
    outDir: path.resolve(hostRoot, '../templates/sunbird-vue-dist'),
    emptyOutDir: true,
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
      },
    },
  },
}))
