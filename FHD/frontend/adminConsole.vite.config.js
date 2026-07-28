/**
 * XCMAX 管理端独立 Vite 配置：base=/admin/，产物 templates/admin-vue-dist。
 * 入口：admin-console/index.html → admin-console/src/main.ts → frontend/src/main.ts
 */
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import VueI18nPlugin from '@intlify/unplugin-vue-i18n/vite'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'
import {
  createAdminConsoleAtAliasPlugin,
  createWorkflowComponentsAliasPlugin,
} from './vite.shared-alias.js'
import { resolveApiBase } from './vite/resolveApiBase.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const hostRoot = __dirname
const adminRoot = path.resolve(hostRoot, '../admin-console')
const adminSrc = path.join(adminRoot, 'src')
const hostSrc = path.join(hostRoot, 'src')
const hostConstants = path.join(hostSrc, 'constants')

const API_BASE = resolveApiBase(process.env.VITE_API_BASE)
const devPort = Number(process.env.VITE_DEV_PORT || 5011)

const ADMIN_MODS_ROOT = path.resolve(hostRoot, '../mods-admin-runtime')

function modViewsDir(modId) {
  const rel = path.join(modId, 'frontend', 'views')
  const p = path.join(ADMIN_MODS_ROOT, rel)
  if (fs.existsSync(p)) return p
  return p
}

const adminModuleAliases = [
  'constants/adminOperatorNav.ts',
  'constants/personnelModApi.ts',
  'constants/xcmaxDashboardEmbed.ts',
  'views/XCmaxAdminView.vue',
  'views/AutomationPolicyView.vue',
  'views/DutyTimeArchitectureView.vue',
  'views/DutyRosterGraphView.vue',
  'views/ServerFunctionsView.vue',
  'views/ApprovalHubView.vue',
  'views/EmployeeAutonomyView.vue',
  'components/workflow/DutyRosterGraphPanel.vue',
  'components/admin/XCmaxAdminAutonomyTab.vue',
  'components/contract/ContractEsignPanel.vue',
  'api/xcmaxAdmin.ts',
  'api/xcmaxOps.ts',
  'api/xcmaxMarketProxy.ts',
  'api/xcmaxEmployeeAutonomy.ts',
  'api/wechatGroupBridge.ts',
  'api/financeLedger.ts',
  'api/contractLifecycle.ts',
  'composables/useWechatEnterpriseBinding.ts',
  'composables/useWechatGroupBridge.ts',
  'utils/dutyRosterEmployeeList.ts',
].flatMap((sub) => {
  const full = path.join(adminSrc, sub)
  const base = sub.replace(/\.(ts|vue)$/, '')
  return [
    { find: `@/${sub}`, replacement: full },
    { find: `@/${base}`, replacement: full },
  ]
})

function buildDevProxy(apiBase) {
  const modstoreBase = (
    process.env.VITE_MODSTORE_BASE ||
    process.env.XCAGI_MARKET_BASE_URL ||
    'http://127.0.0.1:8788'
  ).replace(/\/$/, '')
  const forwardHost = (proxy) => {
    proxy.on('proxyReq', (proxyReq, req) => {
      const origHost = req.headers['host'] || ''
      if (origHost) {
        proxyReq.setHeader('X-Forwarded-Host', origHost)
      }
    })
  }
  return {
    // 比 /api 更具体：全景页运营线健康 / 自维护 loop 走本地 MODstore，避免 FHD 未挂路由时 404 再跨域打 :8788
    '/api/admin/production-line': {
      target: modstoreBase,
      changeOrigin: true,
      configure: forwardHost,
    },
    '/api/ops': {
      target: modstoreBase,
      changeOrigin: true,
      configure: forwardHost,
    },
    '/api': {
      target: apiBase,
      changeOrigin: true,
      configure: forwardHost,
    },
    '/ws': { target: apiBase, changeOrigin: true, ws: true },
    '/health': { target: apiBase, changeOrigin: true },
    '/xcmax-dashboard': { target: apiBase, changeOrigin: true },
  }
}

export default defineConfig(() => ({
  root: adminRoot,
  plugins: [
    createAdminConsoleAtAliasPlugin(hostRoot),
    createWorkflowComponentsAliasPlugin(hostRoot),
    vue(),
    VueI18nPlugin({
      include: [path.join(hostSrc, 'i18n/locales/**/*.json')],
      runtimeOnly: true,
    }),
    AutoImport({ resolvers: [ElementPlusResolver()], dts: false }),
    Components({ resolvers: [ElementPlusResolver({ importStyle: 'css' })], dts: false }),
  ],
  define: {
    'import.meta.env.VITE_XCMAX_ADMIN_CONSOLE': JSON.stringify('1'),
    'import.meta.env.VITE_XCMAX_SUNBIRD_CONSOLE': JSON.stringify(''),
  },
  base: '/admin/',
  resolve: {
    alias: [
      ...adminModuleAliases,
      {
        find: '@/components/admin',
        replacement: path.join(adminSrc, 'components/admin'),
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
      {
        find: '@/data/workflow-employee-docs.json',
        replacement: path.join(hostRoot, 'public/workflow-employee-docs.json'),
      },
      {
        find: '@/data/workflow-employees.json',
        replacement: path.join(hostRoot, 'public/workflow-employees.json'),
      },
      {
        find: '@admin-console-inject/adminHostRoutes',
        replacement: path.join(adminSrc, 'adminHostRoutes.ts'),
      },
      {
        find: '@admin-console-inject/views/DutyRosterGraphView.vue',
        replacement: path.join(adminSrc, 'views/DutyRosterGraphView.vue'),
      },
      { find: '@host', replacement: hostSrc },
      { find: '@', replacement: hostSrc },
      { find: '@amin', replacement: path.resolve(hostRoot, '../AMIN') },
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
    fs: { allow: [adminRoot, hostRoot, path.resolve(hostRoot, '..')] },
  },
  preview: {
    host: '0.0.0.0',
    port: devPort,
    proxy: buildDevProxy(API_BASE),
  },
  publicDir: path.join(hostRoot, 'public'),
  esbuild: {
    target: 'esnext',
  },
  worker: {
    format: 'es',
  },
  optimizeDeps: {
    include: ['vue'],
    // mermaid@11 parser uses modern destructuring that breaks chrome87 prebundle target
    exclude: ['mermaid', '@mermaid-js/parser'],
    esbuildOptions: {
      target: 'esnext',
    },
  },
  build: {
    target: 'esnext',
    outDir: path.resolve(hostRoot, '../templates/admin-vue-dist'),
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
