import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { copyFileSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const ORT_WASM_FILES = [
  'ort-wasm-simd-threaded.asyncify.wasm',
  'ort-wasm-simd-threaded.asyncify.mjs',
] as const

/** 复制 ONNX Runtime WASM 到 dist/asr-ort/，供 Whisper Worker 用固定 URL 加载（避免 hash 文件名 404） */
function copyOrtWasmAssets() {
  return {
    name: 'copy-ort-wasm-assets',
    closeBundle() {
      const srcDir = path.resolve(__dirname, 'node_modules/onnxruntime-web/dist')
      const destDir = path.resolve(__dirname, 'dist/asr-ort')
      try {
        rmSync(destDir, { recursive: true, force: true })
      } catch {
        /* ignore */
      }
      mkdirSync(destDir, { recursive: true })
      for (const name of ORT_WASM_FILES) {
        const src = path.join(srcDir, name)
        if (!existsSync(src)) {
          console.warn(`[copy-ort-wasm] missing ${src}`)
          continue
        }
        const dest = path.join(destDir, name)
        try {
          copyFileSync(src, dest)
        } catch (err) {
          console.warn(`[copy-ort-wasm] copy failed ${name}:`, err)
        }
      }
    },
  }
}

const apiProxyTarget =
  (process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8765').trim() ||
  'http://127.0.0.1:8765'

export function normalizeBase(raw: string | undefined): string {
  const t = (raw || '').trim()
  if (!t) return '/'
  const withSlash = t.endsWith('/') ? t : `${t}/`
  return withSlash.startsWith('/') ? withSlash : `/${withSlash}`
}

export default defineConfig(({ command }) => {
  const envRaw = (process.env.VITE_PUBLIC_BASE || '').trim()
  const base =
    command === 'build'
      ? normalizeBase(envRaw || '/market/')
      : envRaw
        ? normalizeBase(envRaw)
        : '/'

  return {
    plugins: [vue(), copyOrtWasmAssets()],
    base,
    assetsInclude: ['**/*.wasm'],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    build: {
      emptyOutDir: true,
      assetsInlineLimit: 0,
      // Most >500 kB chunks are lazy-loaded diagram/rendering libraries
      // (mermaid/cytoscape/katex/html2canvas). Keep deploy logs focused on
      // unexpected regressions rather than known on-demand payloads.
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks(id: string): string | undefined {
            if (id.includes('node_modules')) {
              if (id.includes('/vue/') || id.includes('/vue-router/') || id.includes('/pinia/')) {
                return 'vue-vendor'
              }
              if (id.includes('/@vue-flow/')) {
                return 'vue-flow'
              }
              if (id.includes('/cytoscape/')) {
                return 'diagram-cytoscape'
              }
              if (id.includes('/katex/')) {
                return 'diagram-katex'
              }
              if (id.includes('/html2canvas/')) {
                return 'capture-html2canvas'
              }
              if (id.includes('/@dagrejs/dagre/')) {
                return 'layout-dagre'
              }
              if (id.includes('/lodash-es/') || id.includes('/lodash/')) {
                return 'lodash-vendor'
              }
              if (id.includes('/@huggingface/') || id.includes('/onnxruntime-web/')) {
                return 'asr-whisper'
              }
            }
            return undefined
          },
        }
      }
    },
    server: {
      port: 5176,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          ws: true,
        },
        '/v1': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/dev-docs': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        '/hf-hub': {
          target: 'https://huggingface.co',
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/market\/hf-hub|^\/hf-hub/, ''),
        },
      },
    },
  }
})
