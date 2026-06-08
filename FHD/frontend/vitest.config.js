import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { webcrypto } from 'node:crypto'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 兼容部分 Windows/Node 环境：Vitest 启动阶段需要 crypto.getRandomValues。
if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== 'function') {
  Object.defineProperty(globalThis, 'crypto', {
    value: webcrypto,
    configurable: true,
  })
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@mod-views/xcagi-planner-bridge/ChatView.vue': path.resolve(
        __dirname,
        './src/test-stubs/ModChatViewStub.vue'
      ),
    },
  },
  test: {
    setupFiles: ['./vitest.setup.ts'],
    globals: true,
    environment: 'jsdom',
    testTimeout: 30_000,
    include: [
      'src/**/*.test.js',
      'src/**/*.test.ts',
      'tests/**/*.test.js',
      'tests/**/*.test.ts',
      'tests/smoke/**/*.test.js',
    ],
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      // ChatView 已薄 shim 至 Mod；原 pro-task-status 用例待迁到 mod 或 useChatView 单测
      'src/views/ChatView.proTaskStatus.test.js',
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: [
        'src/constants/coreMenuCatalog.ts',
        'src/constants/genericModPack.ts',
        'src/constants/platformShellMode.ts',
        'src/constants/loginBranding.ts',
        'src/constants/protectedMods.ts',
        'src/stores/appShell.ts',
        'src/stores/workflowAiEmployees.ts',
        'src/tutorial/buildModSteps.ts',
        'src/tutorial/buildNavTour.ts',
        'src/tutorial/stepFactory.ts',
        'src/composables/useStartupSplash.ts',
        'src/composables/useAppProMode.ts',
        'src/composables/useAppShellBridge.ts',
        // utils：仅纳入已有单测的模块（其余见 COVERAGE_RAMP 待补清单）
        'src/utils/startupRedirect.ts',
        'src/utils/roleMenuProfile.ts',
        'src/utils/coreNavLabel.ts',
        'src/utils/pinSidebarMenuItemsTop.ts',
        'src/utils/erpDomainPaths.ts',
        'src/utils/customerServicePagePaths.ts',
        'src/utils/workflowNav.ts',
        'src/utils/modWorkflowEmployees.ts',
        'src/utils/kittenDatasetParser.ts',
        'src/utils/approvalPaths.ts',
        'src/utils/sidebarApiRegression.ts',
        'src/utils/mergeSidebarMenuItems.ts',
        'src/utils/workflowEmployeeDocs.ts',
        'src/utils/modelPaymentPaths.ts',
        'src/utils/lanPaths.ts',
        'src/utils/plannerPagePaths.ts',
        'src/utils/erpPagePaths.ts',
        'src/utils/workflowPagePaths.ts',
        'src/utils/approvalPagePaths.ts',
        'src/utils/modelPaymentPagePaths.ts',
        'src/utils/adminConsoleUrl.ts',
        'src/utils/apiBase.ts',
        'src/utils/xcagiStorageKeys.ts',
      ],
      exclude: ['src/**/*.test.js', 'src/**/*.test.ts'],
      /** 全仓含大量 .vue 占位行；阈值略高于当前基线，新增 utils/store 单测后应稳定通过 */
      /** 目标 50%+（见 COVERAGE_RAMP / v10 线内迭代） */
      thresholds: {
        lines: 50,
        branches: 30,
        functions: 35,
        statements: 50,
      },
    },
  },
})
