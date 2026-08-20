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
      // 全量行为测试拉到 2026-08-17 的可验证基线后，用整数下限锁住回归。
      // 当前实测：74.82 / 59.44 / 69.18 / 77.50。
      thresholds: {
        statements: 74,
        branches: 59,
        functions: 69,
        lines: 77,
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
