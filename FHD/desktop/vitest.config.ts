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
      reporter: ['text', 'json', 'html'],
      include: ['main.ts', 'updater.ts', 'rollback.ts'],
      exclude: ['**/*.test.ts', 'build/**', 'resources/**', 'dist/**']
    }
  }
})
