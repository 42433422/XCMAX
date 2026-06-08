import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const corpOutDir = path.resolve(__dirname, '../../corp-butler')

function copyBrandLogo() {
  return {
    name: 'copy-corp-butler-brand',
    closeBundle() {
      const src = path.resolve(__dirname, 'public/brand-xc-logo.jpg')
      const dest = path.join(corpOutDir, 'brand-xc-logo.jpg')
      if (!existsSync(src)) return
      mkdirSync(corpOutDir, { recursive: true })
      copyFileSync(src, dest)
    },
  }
}

export default defineConfig({
  plugins: [vue(), copyBrandLogo()],
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
