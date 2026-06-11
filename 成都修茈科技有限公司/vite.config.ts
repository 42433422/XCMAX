import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

const productionBase = (): string => {
  const raw = (process.env.VITE_PUBLIC_BASE || '').trim()
  if (!raw) return '/'
  const withSlash = raw.endsWith('/') ? raw : `${raw}/`
  return withSlash.startsWith('/') ? withSlash : `/${withSlash}`
}

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  base: command === 'build' ? productionBase() : '/',
  resolve: {
    alias: {
      '@': new URL('./src', import.meta.url).pathname,
    },
  },
  server: {
    port: 5176,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
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
      // 起步 "不退步" 基线：当前根项目仅 stores + api 有单元测试，多数 .vue 视图尚无组件测试。
      // 此处门槛严格按当前实测值 -0.3% 设置，目的是阻止覆盖率回退；后续每补一批测试就把门槛抬高。
      thresholds: {
        statements: 3,
        branches: 60,
        functions: 18,
        lines: 3,
      },
    },
  },
}))
