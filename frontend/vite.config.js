import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

const copyStaticPlugin = () => ({
  name: 'copy-static',
  closeBundle() {
    const srcDir = path.resolve(__dirname, '../AI助手/static')
    const destDir = path.resolve(__dirname, 'public/static')

    if (fs.existsSync(srcDir)) {
      copyDir(srcDir, destDir)
      console.log('Static files copied successfully!')
    }
  }
})

function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true })
  }

  const entries = fs.readdirSync(src, { withFileTypes: true })

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath)
    } else {
      fs.copyFileSync(srcPath, destPath)
    }
  }
}

// 读取环境变量中的后端地址（支持局域网）
// .env.local 里加一行: VITE_API_BASE=http://192.168.x.x:5000
const API_BASE = process.env.VITE_API_BASE || 'http://127.0.0.1:5000'

/** 手机访问局域网 IP 时，HMR WebSocket 不能仍指向 localhost；由 start-lan.ps1 注入本机私网 IP。 */
const devHmrHost = (process.env.VITE_DEV_HMR_HOST || '').trim()

export default defineConfig(({ mode }) => {
  // 加载环境变量
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiBase = env.VITE_API_BASE || API_BASE
  const publicBase = env.VITE_PUBLIC_BASE || '/'
  const isDev = mode === 'development'

  const hmr =
    isDev && devHmrHost && devHmrHost !== '127.0.0.1'
      ? {
          overlay: false,
          host: devHmrHost,
          port: 5001,
          clientPort: 5001,
        }
      : { overlay: false }

  return {
    plugins: [vue(), copyStaticPlugin()],
    base: publicBase,
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    server: {
      // 0.0.0.0：明确监听 IPv4 全接口，避免个别环境下 host:true 局域网设备连不上 :5001
      host: isDev ? '0.0.0.0' : true,
      // 与 XCAGI/run.py（5000）配合：/api 走下方代理。勿与 run_warehouse.py（默认 5002）混用同一端口。
      port: 5001,
      // 避免部分环境下以「主机名 / IP」访问时被 Vite 拒绝（局域网联调）
      ...(isDev ? { allowedHosts: true } : {}),
      hmr,
      proxy: {
        // 开发时统一把业务 API 代理到完整后端 run.py（5000）。材料拆分进程见 run_warehouse.py（默认 5002），勿占用 5001（Vite）。
        // 规则：尽量使用"更具体的前缀 -> 5000"，最后用 '/api' 兜底到 5000。

        // compat：/orders/*（不带 /api 前缀）。注意 Vue 路由也有页面 /orders，浏览器刷新须走 SPA。
        '/orders': {
          target: apiBase,
          changeOrigin: true,
          bypass(req) {
            const accept = req.headers.accept || ''
            if (req.method === 'GET' && accept.includes('text/html')) {
              return '/index.html'
            }
          },
        },

        // compat：/health
        '/health': {
          target: apiBase,
          changeOrigin: true,
        },

        // 出货/打印/AI/chat/以及 compat 中的相关接口都走 5000
        '/api/shipment': {
          target: apiBase,
          changeOrigin: true,
        },
        // Planner SSE：默认代理超时过短可能中断长连接
        '/api/ai': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        '/api/print': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/generate': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/orders': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/shipment-records': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/purchase_units': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/product_names': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/printers': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/sales-contract': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/price-list': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/tts': {
          target: apiBase,
          changeOrigin: true,
        },
        // FHD 风格上传（对话 @ Excel 等）：须由 FastAPI 5000 提供
        '/api/upload': {
          target: apiBase,
          changeOrigin: true,
          timeout: 120000,
          proxyTimeout: 120000,
        },

        // 兼容：基础数据/聊天/联系人等也应转发到 5000
        // 否则会落入兜底 '/api'，若 5000 未启动则代理失败（终端见 [vite-proxy] 日志）
        '/api/conversations': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/wechat_contacts': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        '/api/products': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/materials': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/system': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/state': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/intent-packages': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/tools': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/wechat': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/db-tools': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/templates': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        // 传统模式 watch 为长连接流式响应；默认超时过短易出现 504
        '/api/traditional-mode': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        // 奇士美 PRO Mod（含 /api/mod/sz-qsm-pro/phone-agent/*）；代理层失败时返回 JSON 502，避免与后端 500 混淆
        '/api/mod': {
          target: apiBase,
          changeOrigin: true,
          configure: (proxy) => {
            proxy.on('error', (err, _req, res) => {
              console.error(
                '[vite-proxy] /api/mod -> ' + apiBase + ' failed:',
                err && err.message ? err.message : err
              )
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error:
                      '无法连接后端 ' + apiBase + '。请先在本机启动：python run.py（工作目录 XCAGI）。',
                  })
                )
              }
            })
          },
        },

        // Mod 系统（显式规则，避免个别环境下 /api 兜底未命中或错误码不直观）
        '/api/mods': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
          configure: (proxy) => {
            proxy.on('error', (err, _req, res) => {
              console.error(
                '[vite-proxy] /api/mods -> ' + apiBase + ' failed:',
                err && err.message ? err.message : err
              )
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error:
                      '无法连接后端 ' + apiBase + '。请先在本机启动：python run.py（工作目录 XCAGI）。',
                  })
                )
              }
            })
          },
        },

        // 兜底：其余所有 /api 都发给后端服务（5000）。若浏览器大量 500/502，先确认已执行：python run.py
        '/api': {
          target: apiBase,
          changeOrigin: true,
          ws: true,
          configure: (proxy) => {
            // 把真实客户端 IP 透传给后端，让 LAN Guard 能拿到正确的来源地址
            proxy.on('proxyReq', (proxyReq, req) => {
              const clientIp = req.socket?.remoteAddress || req.headers['x-forwarded-for'] || ''
              const normalizedIp = clientIp.replace(/^::ffff:/, '')
              if (normalizedIp) {
              proxyReq.setHeader('X-Forwarded-For', normalizedIp)
              proxyReq.setHeader('X-Real-IP', normalizedIp)
              }
            })
            proxy.on('error', (err, _req, res) => {
              console.error(
                '[vite-proxy] /api -> ' + apiBase + ' failed:',
                err && err.message ? err.message : err
              )
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error:
                      '无法连接后端 ' + apiBase + '。请先在本机启动：python run.py（工作目录 XCAGI）。'
                  })
                )
              }
            })
          }
        },
      }
    },
    publicDir: 'public',
    worker: {
      format: 'es'
    },
    build: {
      outDir: '../templates/vue-dist',
      assetsDir: 'assets',
      emptyOutDir: true,
      rollupOptions: {
        output: {
          manualChunks: {
            'vendor-vue': ['vue'],
            'vendor-stores': [
              './src/stores/proMode.ts',
              './src/stores/jarvisChat.ts',
              './src/stores/productQuery.ts',
              './src/stores/workMode.ts'
            ]
          },
          chunkFileNames: 'assets/js/[name]-[hash].js',
          entryFileNames: 'assets/js/[name]-[hash].js',
          assetFileNames: (assetInfo) => {
            const info = assetInfo.name.split('.')
            const ext = info[info.length - 1]
            if (/\.(css)$/.test(assetInfo.name)) {
              return 'assets/css/[name]-[hash][extname]'
            }
            if (/\.(woff2?|eot|ttf|otf)$/.test(assetInfo.name)) {
              return 'assets/fonts/[name]-[hash][extname]'
            }
            return 'assets/[name]-[hash][extname]'
          }
        },
        onwarn(warning, warn) {
          if (warning.message && warning.message.includes('dynamic import will not move module into another chunk')) {
            return
          }
          warn(warning)
        },
      },
      // 使用 Vite 默认的 esbuild 压缩，避免对 terser 额外依赖
      minify: 'esbuild',
      sourcemap: false,
      cssCodeSplit: true,
      target: 'es2015',
      reportCompressedSize: true
    },
    optimizeDeps: {
      include: ['vue'],
      exclude: []
    },
    css: {
      devSourcemap: true
    }
  }
})
