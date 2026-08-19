import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

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
  optimizeDeps: {
    // esbuild 0.28 drops transforms for some legacy browser targets; this app
    // already targets modern browsers/Electron in production, so keep the dev
    // dependency pre-bundle on the same target as the production build.
    esbuildOptions: {
      target: 'esnext',
    },
  },
  build: {
    // 当前客户端为现代浏览器/Electron；避免将 Vue 已生成的辅助模块
    // 再交给新版 esbuild 做不必要的解构降级。
    target: 'esnext',
    // 根目录 index.html 是公司静态官网；Vue 市场应用使用独立入口，
    // 避免 Vite 把官网已生成的非模块脚本当作源码再转译。
    rollupOptions: {
      input: fileURLToPath(new URL('./app.html', import.meta.url)),
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
      // API、路由、状态仓库和所有视图均纳入行为测试；四项指标统一守住 80%。
      thresholds: {
        statements: 80,
        branches: 80,
        functions: 80,
        lines: 80,
      },
    },
  },
}))
