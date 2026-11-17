import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

// Ship the pinned SDK assets and notices together, without vendoring generated binaries.
export function openimAssets() {
  const require = createRequire(import.meta.url)
  const root = path.resolve(path.dirname(require.resolve('@openim/wasm-client-sdk')), '..')
  const files = Object.fromEntries(['openIM.wasm', 'sql-wasm.wasm', 'wasm_exec.js']
    .map(name => [name, path.join(root, 'assets', name)]))
  files['LICENSE'] = path.join(root, 'LICENSE')
  return {
    name: 'openim-sdk-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const match = req.url?.split('?')[0].match(/\/openim\/([^/]+)$/)
        const file = match && files[match[1]]
        if (!file) return next()
        res.setHeader('Content-Type', file.endsWith('.wasm') ? 'application/wasm' : 'text/javascript')
        fs.createReadStream(file).pipe(res)
      })
    },
    generateBundle() {
      for (const [name, file] of Object.entries(files)) {
        this.emitFile({ type: 'asset', fileName: `openim/${name}`, source: fs.readFileSync(file) })
      }
    },
  }
}
