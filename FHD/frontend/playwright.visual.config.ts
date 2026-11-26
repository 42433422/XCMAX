import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './visual-regression', forbidOnly: true, retries: 0, workers: 1,
  timeout: 90000, reporter: 'list',
  use: {
    browserName: 'chromium', baseURL: 'http://127.0.0.1:5001',
    deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai',
    colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block',
    launchOptions: {
      // Keep text and layer rasterization independent of compositor scheduling.
      args: [
        '--no-proxy-server', '--disable-skia-runtime-opts', '--disable-gpu',
        '--disable-lcd-text', '--disallow-non-exact-resource-reuse',
        '--run-all-compositor-stages-before-draw', '--disable-partial-raster',
        '--num-raster-threads=1',
      ],
    },
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 5001 --strictPort',
    url: 'http://127.0.0.1:5001', reuseExistingServer: false, timeout: 180000,
  },
})
