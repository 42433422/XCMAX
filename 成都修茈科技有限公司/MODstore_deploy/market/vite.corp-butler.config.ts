import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const corpOutDir = path.resolve(__dirname, '../../corp-butler')

function copyCorpStaticAssets() {
  return {
    name: 'copy-corp-butler-static',
    closeBundle() {
      mkdirSync(corpOutDir, { recursive: true })
      // emptyOutDir 会清掉产物目录；官网悬浮球头像必须随包落盘（/corp-butler/*.png）
      const files = [
        'brand-xc-logo.jpg',
        'ai-butler-female-avatar-v1.png',
        'ai-butler-male-avatar-v1.jpg',
      ]
      for (const name of files) {
        const src = path.resolve(__dirname, 'public', name)
        if (!existsSync(src)) continue
        copyFileSync(src, path.join(corpOutDir, name))
      }
    },
  }
}

export default defineConfig({
  plugins: [vue(), copyCorpStaticAssets()],
  base: '/corp-butler/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: corpOutDir,
    emptyOutDir: true,
    assetsInlineLimit: 4096,
    rollupOptions: {
      input: path.resolve(__dirname, 'src/corp-butler/main.ts'),
      output: {
        entryFileNames: 'corp-butler.js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          const name = assetInfo.name || ''
          if (name.endsWith('.css')) return 'corp-butler.css'
          return 'assets/[name]-[hash][extname]'
        },
      },
    },
  },
})
