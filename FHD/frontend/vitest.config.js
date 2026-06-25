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
    alias: [
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
        find: '@mod-views/xcagi-planner-bridge/ChatView.vue',
        replacement: path.resolve(__dirname, './src/test-stubs/ModChatViewStub.vue'),
      },
      {
        find: '@admin-console-inject/views/DutyRosterGraphView.vue',
        replacement: path.resolve(__dirname, './src/views/adminDutyRosterGraphView.stub.vue'),
      },
      { find: '@', replacement: path.resolve(__dirname, './src') },
    ],
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
      reporter: ['text', 'json', 'json-summary', 'html'],
      // 铁律1：全量口径 src/**，禁止再用窄 include 凑数（2026-06-14）。
      // 覆盖率提升只能靠补测，不得靠缩小统计范围。
      include: ['src/**/*.{ts,js,vue}'],
      exclude: [
        'src/**/*.test.{js,ts}',
        'src/**/*.spec.{js,ts}',
        'src/**/*.d.ts',
        'src/**/__tests__/**',
        'src/test-stubs/**',
        'src/main.ts',
        'src/**/*.worker.ts',
        'src/i18n/locales/**',
      ],
      // 阈值 = 全量诚实基线。floor 只升不降，由
      // scripts/dev/coverage_ratchet.py 维护。历史 50/30/35/50 来自窄 include，不可比，已退役。
      // 2026-06-19：statements 达到 90% 目标，棘轮提升至 90/80/77/90。
      // 2026-06-20：6 个组件 236 测试补齐，functions 78.5% > 76%，棘轮提升 functions 至 78。
      // 2026-06-21：删除 coverage.ramp.test.ts（2496 行盲调凑数）+ zeroCoverage.mount.test.ts（仅
      //   断言 exists），挤水分后真实基线为 79.67/78.89/76/79.67，棘轮重置至诚实值。
      // 2026-06-24：全量补测（~1100+ 测试，60+ 文件）恢复真实覆盖至 89.64/79.75/77.9/89.64，
      //   阈值恢复至 ratchet baseline floor（89/79/77/89），棘轮门禁通过。
      thresholds: {
        lines: 89,
        branches: 79,
        functions: 77,
        statements: 89,
      },
    },
  },
})
