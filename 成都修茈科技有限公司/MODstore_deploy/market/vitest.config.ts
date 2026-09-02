import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.spec.ts'],
    exclude: ['src/e2e/**', 'dist/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,vue}'],
      exclude: [
        'src/main.ts',
        'src/**/*.d.ts',
        'src/test/**',
        'src/e2e/**',
        // 独立的“客来来”React/Electron 工作区自带 package.json 与测试配置，
        // 不属于 Market 的 Vite 产物，不能混入 Market 覆盖率分母。
        'src/domain/客来来/**',
        'src/**/*.test.ts',
        'src/**/*.spec.ts',
      ],
      // 全量行为测试拉到基线后，用整数下限锁住回归。
      // 2026-09-02 实测（大文件拆分 +482 函数摊薄后回落，分支覆盖在 56.99–57.01 间抖动）：
      // 73.76–73.79 / 56.99–57.01 / 65.66 / 76.36–76.40，
      // 按整数下限重设为 73 / 56 / 65 / 76，只升不降。
      thresholds: {
        statements: 73,
        branches: 56,
        functions: 65,
        lines: 76,
        'src/application/paymentApi.ts': {
          statements: 80,
          branches: 70,
          functions: 80,
          lines: 80,
        },
      },
    },
  },
})
