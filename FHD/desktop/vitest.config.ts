import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['**/*.test.ts'],
    exclude: ['node_modules/**', 'dist/**', 'build/**', 'resources/**'],
    globals: false,
    restoreMocks: true,
    clearMocks: true,
    env: {
      XCAGI_DESKTOP_TEST: '1'
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'json-summary'],
      include: ['**/*.ts'],
      exclude: [
        '**/*.test.ts',
        '**/__tests__/**',
        'build/**',
        'resources/**',
        'dist/**',
        'node_modules/**',
        'e2e/**',
        'vitest.config.ts',
        'playwright.config.ts',
        // 纯类型声明（编译后无运行时代码），不计入覆盖率
        'autonomy/types.ts',
        // contextBridge 纯桥接层，由 Playwright-Electron E2E 真实链路覆盖
        'preload.ts'
      ],
      // 全模块覆盖率门禁（2026-08 实测基线 52/77/62/52，只允许上升）：
      // 窗口/IPC/bootstrap 等主进程胶水代码由 E2E 覆盖，单测门禁守纯逻辑模块。
      thresholds: {
        lines: 50,
        branches: 75,
        functions: 60,
        statements: 50
      }
    }
  }
})
