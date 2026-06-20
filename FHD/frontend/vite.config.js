import { defineConfig, loadEnv } from 'vite'
import path from 'path'
import { buildDevProxy } from './vite/devProxy.js'
import { createBuildOptions } from './vite/build.js'
import { createVitePlugins } from './vite/plugins.js'
import { createStaticCopyPlugin, modViewsDir } from './vite/staticCopy.js'
import { resolveApiBase } from './vite/resolveApiBase.js'

const API_BASE = resolveApiBase(process.env.VITE_API_BASE)
const devHmrHost = (process.env.VITE_DEV_HMR_HOST || '').trim()

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiBase = env.VITE_API_BASE || API_BASE
  const publicBase = env.VITE_PUBLIC_BASE || '/'
  const isDev = mode === 'development'
  const xcmaxPublicApiPrefix = String(env.VITE_XCMAX_PUBLIC_API_PREFIX || '').trim()

  let devPort = 42423
  const rawDevPort = String(env.VITE_DEV_PORT || '').trim()
  if (rawDevPort) {
    const p = Number.parseInt(rawDevPort, 10)
    if (Number.isFinite(p) && p > 0) devPort = p
  }

  const hmrHost = devHmrHost || '127.0.0.1'
  const hmr = isDev
    ? {
      overlay: false,
      host: hmrHost,
      port: devPort,
      clientPort: devPort,
      protocol: 'ws',
    }
    : { overlay: false }

  const productSku = String(env.VITE_XCAGI_PRODUCT_SKU || '').trim().toLowerCase()
  // 企业宿主需要预打包桥接路由与账号定制路由；通用版保持干净空 glob。
  const editionSuffix =
    mode === 'minimal'
      ? 'minimal'
      : productSku === 'enterprise'
        ? 'enterprise'
        : mode === 'generic'
          ? 'generic'
          : 'full'
  const constantsDir = path.resolve(__dirname, './src/constants')

  return {
    plugins: createVitePlugins({
      staticCopyPlugin: createStaticCopyPlugin(__dirname),
      xcmaxPublicApiPrefix,
    }),
    base: publicBase,
    resolve: {
      alias: [
        {
          find: '@/constants/hostViewGlob',
          replacement: path.join(constantsDir, `hostViewGlob.${editionSuffix}.ts`),
        },
        {
          find: '@/constants/modPhysicalViewGlob',
          replacement: path.join(constantsDir, `modPhysicalViewGlob.${editionSuffix}.ts`),
        },
        {
          find: '@/constants/modRouteGlob',
          replacement: path.join(constantsDir, `modRouteGlob.${editionSuffix}.ts`),
        },
        {
          find: '@/data/workflow-employee-docs.json',
          replacement: path.resolve(__dirname, './public/workflow-employee-docs.json'),
        },
        {
          find: '@/data/workflow-employees.json',
          replacement: path.resolve(__dirname, './public/workflow-employees.json'),
        },
        {
          find: '@admin-console-inject/adminHostRoutes',
          replacement: path.resolve(__dirname, './src/router/adminHostRoutes.stub.ts'),
        },
        {
          find: '@admin-console-inject/views/DutyRosterGraphView.vue',
          replacement: path.resolve(__dirname, './src/views/adminDutyRosterGraphView.stub.vue'),
        },
        { find: '@', replacement: path.resolve(__dirname, './src') },
        // 干净通用版：Mod 已迁出 mods-export-2026-06-07/，开发时按需恢复单条 alias
        // {
        //   find: '@mod-views/xcagi-lan-license-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-lan-license-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-customer-service-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-customer-service-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-approval-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-approval-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-planner-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-planner-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-model-payment-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-model-payment-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-erp-domain-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-erp-domain-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-office-employee-pack-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-office-employee-pack-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-workflow-visualization-bridge',
        //   replacement: modViewsDir(__dirname, 'xcagi-workflow-visualization-bridge'),
        // },
        // {
        //   find: '@mod-views/xcagi-core-workflow-employees',
        //   replacement: modViewsDir(__dirname, 'xcagi-workflow-visualization-bridge'),
        // },
        { find: 'vue-router', replacement: path.resolve(__dirname, 'node_modules/vue-router') },
        { find: 'pinia', replacement: path.resolve(__dirname, 'node_modules/pinia') },
        { find: 'element-plus', replacement: path.resolve(__dirname, 'node_modules/element-plus') },
        { find: 'xlsx', replacement: path.resolve(__dirname, 'node_modules/xlsx') },
      ],
      dedupe: ['vue', 'vue-router', 'pinia', 'element-plus', 'xlsx'],
    },
    server: {
      // 0.0.0.0：明确监听 IPv4 全接口，避免个别环境下 host:true 局域网设备连不上 :5001
      host: isDev ? '0.0.0.0' : true,
      // 与 XCAGI/run.py（默认 5000）配合：/api 走下方代理。第二套本地实例见仓库根 .env.example「个人实例」。
      port: devPort,
      // 避免部分环境下以「主机名 / IP」访问时被 Vite 拒绝（局域网联调）
      ...(isDev ? { allowedHosts: true } : {}),
      hmr,
      proxy: buildDevProxy(apiBase),
      fs: {
        allow: ['..'],
      },
    },

    preview: {
      host: '0.0.0.0',
      port: devPort,
      strictPort: false,
      proxy: buildDevProxy(apiBase),
    },
    publicDir: 'public',
    worker: {
      format: 'es'
    },
    build: createBuildOptions(),
    optimizeDeps: {
      include: ['vue'],
      exclude: []
    },
    css: {
      devSourcemap: true
    }
  }
})
