/**
 * XCMAX 管理端独立 Vite 配置：base=/admin/，产物 templates/admin-vue-dist。
 * 入口：admin-console/index.html → admin-console/src/main.ts → frontend/src/main.ts
 */
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
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

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const hostRoot = __dirname
const adminRoot = path.resolve(hostRoot, '../admin-console')
const adminSrc = path.join(adminRoot, 'src')
const hostSrc = path.join(hostRoot, 'src')
const hostConstants = path.join(hostSrc, 'constants')

const API_BASE = process.env.VITE_API_BASE || 'http://127.0.0.1:5000'
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
  'components/workflow/DutyRosterGraphPanel.vue',
  'components/contract/ContractEsignPanel.vue',
  'api/xcmaxAdmin.ts',
  'api/xcmaxOps.ts',
  'api/xcmaxMarketProxy.ts',
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
  return {
    '/api': { target: apiBase, changeOrigin: true },
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
  worker: {
    format: 'es',
  },
  build: {
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
