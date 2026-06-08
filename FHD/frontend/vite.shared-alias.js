import path from 'path'
import fs from 'fs'

const AT_ALIAS_EXTS = ['.ts', '.tsx', '.vue', '.js', '.mjs', '.json']

function resolveAtAliasFile(basePath) {
  if (fs.existsSync(basePath) && fs.statSync(basePath).isFile()) return basePath
  for (const ext of AT_ALIAS_EXTS) {
    const withExt = basePath + ext
    if (fs.existsSync(withExt)) return withExt
  }
  for (const ext of AT_ALIAS_EXTS) {
    const indexFile = path.join(basePath, `index${ext}`)
    if (fs.existsSync(indexFile)) return indexFile
  }
  return null
}

/**
 * 企业版 :5001 内嵌 admin-console 视图时，将 admin-console 文件内的 `@/` 解析到 admin-console/src。
 * 须在默认 `@` → frontend/src alias 之前生效（enforce: 'pre'）。
 */
export function createAdminConsoleAtAliasPlugin(frontendDir) {
  const adminSrc = path.resolve(frontendDir, '../admin-console/src')

  return {
    name: 'xcmax-admin-console-at-alias',
    enforce: 'pre',
    resolveId(source, importer) {
      if (!importer || !source.startsWith('@/')) return null
      const normImporter = importer.replace(/\\/g, '/')
      if (!normImporter.includes('admin-console')) return null
      const rel = source.slice(2)
      const resolved = resolveAtAliasFile(path.join(adminSrc, rel))
      return resolved
    },
  }
}

/**
 * `@/components/workflow/*` 在 frontend 与 admin-console 各有一份；优先 frontend，缺失时回退 admin-console。
 * 避免整目录 alias 到 admin 导致员工空间白屏，也避免 build 时 DutyRosterGraphPanel 解析失败。
 */
export function createWorkflowComponentsAliasPlugin(frontendDir) {
  const frontendWorkflow = path.resolve(frontendDir, './src/components/workflow')
  const adminWorkflow = path.resolve(frontendDir, '../admin-console/src/components/workflow')
  const prefix = '@/components/workflow/'

  return {
    name: 'xcmax-workflow-components-alias',
    enforce: 'pre',
    resolveId(source) {
      if (!source.startsWith(prefix)) return null
      const rel = source.slice(prefix.length)
      return (
        resolveAtAliasFile(path.join(frontendWorkflow, rel)) ||
        resolveAtAliasFile(path.join(adminWorkflow, rel))
      )
    },
  }
}

/** FHD/mods 优先；缺失时回退到 FHD/XCAGI/mods。 */
export function modViewsDir(frontendDir, modId) {
  const rel = path.join(modId, 'frontend', 'views')
  const candidates = [
    path.resolve(frontendDir, '../mods', rel),
    path.resolve(frontendDir, '../XCAGI/mods', rel),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return candidates[0]
}

/**
 * Vite / Vitest 共用 resolve.alias。
 * @param {string} frontendDir - FHD/frontend 绝对路径
 * @param {{ editionSuffix?: string }} [opts]
 */
export function createResolveAlias(frontendDir, opts = {}) {
  const editionSuffix = opts.editionSuffix || 'full'
  const constantsDir = path.resolve(frontendDir, './src/constants')
  const adminSrc = path.resolve(frontendDir, '../admin-console/src')
  const nodeModules = path.resolve(frontendDir, 'node_modules')

  return [
    {
      find: '@admin-console-inject/adminHostRoutes',
      replacement: path.join(frontendDir, 'src/router/adminHostRoutes.stub.ts'),
    },
    {
      find: '@/components/admin',
      replacement: path.join(adminSrc, 'components/admin'),
    },
    {
      find: '@/constants/adminOperatorNav',
      replacement: path.join(adminSrc, 'constants/adminOperatorNav.ts'),
    },
    {
      find: '@/constants/xcmaxDashboardEmbed',
      replacement: path.join(adminSrc, 'constants/xcmaxDashboardEmbed.ts'),
    },
    {
      find: '@/composables/useWechatEnterpriseBinding',
      replacement: path.join(adminSrc, 'composables/useWechatEnterpriseBinding.ts'),
    },
    {
      find: '@/composables/useWechatGroupBridge',
      replacement: path.join(adminSrc, 'composables/useWechatGroupBridge.ts'),
    },
    {
      find: '@/api/xcmaxOps',
      replacement: path.join(adminSrc, 'api/xcmaxOps.ts'),
    },
    {
      find: '@/api/xcmaxMarketProxy',
      replacement: path.join(adminSrc, 'api/xcmaxMarketProxy.ts'),
    },
    {
      find: '@/api/contractLifecycle',
      replacement: path.join(adminSrc, 'api/contractLifecycle.ts'),
    },
    {
      find: '@/utils/dutyRosterEmployeeList',
      replacement: path.join(adminSrc, 'utils/dutyRosterEmployeeList.ts'),
    },
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
    { find: '@', replacement: path.resolve(frontendDir, './src') },
    { find: '@amin', replacement: path.resolve(frontendDir, '../AMIN') },
    {
      find: '@mod-views/xcagi-lan-license-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-lan-license-bridge'),
    },
    {
      find: '@mod-views/xcagi-customer-service-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-customer-service-bridge'),
    },
    {
      find: '@mod-views/xcagi-approval-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-approval-bridge'),
    },
    {
      find: '@mod-views/xcagi-planner-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-planner-bridge'),
    },
    {
      find: '@mod-views/xcagi-model-payment-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-model-payment-bridge'),
    },
    {
      find: '@mod-views/xcagi-erp-domain-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-erp-domain-bridge'),
    },
    {
      find: '@mod-views/xcagi-office-employee-pack-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-office-employee-pack-bridge'),
    },
    {
      find: '@mod-views/xcagi-workflow-visualization-bridge',
      replacement: modViewsDir(frontendDir, 'xcagi-workflow-visualization-bridge'),
    },
    {
      find: '@mod-views/xcagi-core-workflow-employees',
      replacement: modViewsDir(frontendDir, 'xcagi-workflow-visualization-bridge'),
    },
    { find: 'vue-router', replacement: path.join(nodeModules, 'vue-router') },
    { find: 'pinia', replacement: path.join(nodeModules, 'pinia') },
    { find: 'element-plus', replacement: path.join(nodeModules, 'element-plus') },
    { find: 'xlsx', replacement: path.join(nodeModules, 'xlsx') },
    { find: '@vue-flow/core', replacement: path.join(nodeModules, '@vue-flow/core') },
    { find: '@vue-flow/background', replacement: path.join(nodeModules, '@vue-flow/background') },
    { find: '@vue-flow/controls', replacement: path.join(nodeModules, '@vue-flow/controls') },
    { find: '@vue-flow/minimap', replacement: path.join(nodeModules, '@vue-flow/minimap') },
  ]
}
