import { defineConfig, loadEnv } from 'vite'
import { materializeMediaAssets } from '../../scripts/dev/materialize_media_assets.mjs'
import path from 'path'
import { buildDevProxy } from './vite/devProxy.js'
import { createBuildOptions, resolveViteGitSha } from './vite/build.js'
import { createVitePlugins } from './vite/plugins.js'
import { resolveApiBase } from './vite/resolveApiBase.js'

const API_BASE = resolveApiBase(process.env.VITE_API_BASE)
const devHmrHost = (process.env.VITE_DEV_HMR_HOST || '').trim()

export default defineConfig(({ mode }) => {
  materializeMediaAssets('frontend')
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  process.env.VITE_XCAGI_GIT_SHA = resolveViteGitSha(env.VITE_XCAGI_GIT_SHA)
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

  const productSku = String(env.VITE_XCAGI_PRODUCT_SKU || '')
    .trim()
    .toLowerCase()
  // 企业宿主需要预打包桥接路由与账号定制路由；通用版保持干净空 glob。
  const editionSuffix =
    mode === 'minimal' ? 'minimal' : productSku === 'enterprise' ? 'enterprise' : mode === 'generic' ? 'generic' : 'full'
  const constantsDir = path.resolve(__dirname, './src/constants')

  return {
    plugins: createVitePlugins({
      xcmaxPublicApiPrefix,
      i18nInclude: path.resolve(__dirname, './src/i18n/locales/**/*.json'),
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
        // 客服桥接 Mod 自有组件/composable 别名（其物理视图不得用 ../ 相对导入）
        {
          find: '@mod-frontend/xcagi-customer-service-bridge',
          replacement: path.resolve(__dirname, '../mods/xcagi-customer-service-bridge/frontend'),
        },
        { find: 'vue-router', replacement: path.resolve(__dirname, 'node_modules/vue-router') },
        { find: 'pinia', replacement: path.resolve(__dirname, 'node_modules/pinia') },
        { find: 'element-plus', replacement: path.resolve(__dirname, 'node_modules/element-plus') },
        { find: 'xlsx', replacement: path.resolve(__dirname, 'node_modules/xlsx') },
      ],
      dedupe: ['vue', 'vue-router', 'pinia', 'element-plus', 'xlsx'],
    },
    server: {
      // 本地开发仅绑定回环地址，不向局域网或公网开放监听。
      host: isDev ? '127.0.0.1' : true,
      // 与 XCAGI/run.py（默认 5000）配合：/api 走下方代理。第二套本地实例见仓库根 .env.example「个人实例」。
      port: devPort,
      hmr,
      proxy: buildDevProxy(apiBase),
      fs: {
        allow: ['..'],
      },
    },

    preview: {
      host: '127.0.0.1',
      port: devPort,
      strictPort: false,
      proxy: buildDevProxy(apiBase),
    },
    publicDir: 'public',
    worker: {
      format: 'es',
    },
    build: createBuildOptions(),
    optimizeDeps: {
      include: ['vue'],
      exclude: ['vue-router'],
      esbuildOptions: {
        target: 'esnext',
      },
    },
    css: {
      devSourcemap: true,
    },
  }
})
