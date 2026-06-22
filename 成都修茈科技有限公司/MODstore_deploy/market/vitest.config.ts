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
        'src/**/*.test.ts',
        'src/**/*.spec.ts',
      ],
      // 阶梯提升计划：30 → 50 → 80（实际覆盖率 59%，30% 是安全第一台阶）
      thresholds: {
        statements: 30,
        branches: 25,
        functions: 28,
        lines: 30,
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
