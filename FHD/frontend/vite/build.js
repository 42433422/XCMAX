import { execFileSync } from 'node:child_process'

/** Preserve release identity while clearly marking uncommitted local builds. */
export function resolveViteGitSha(explicitSha) {
  const supplied = String(explicitSha || '').trim()
  if (supplied) return supplied
  try {
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
    const dirty = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
    return sha && !dirty ? sha : 'local'
  } catch {
    return 'local'
  }
}

/** Rollup build options extracted from vite.config.js */

/**
 * @returns {import('vite').BuildOptions}
 */
export function createBuildOptions() {
  return {
    outDir: '../templates/vue-dist',
    assetsDir: 'assets',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (/\.(css)$/.test(assetInfo.name || '')) {
            return 'assets/css/[name]-[hash][extname]'
          }
          if (/\.(woff2?|eot|ttf|otf)$/.test(assetInfo.name || '')) {
            return 'assets/fonts/[name]-[hash][extname]'
          }
          return 'assets/[name]-[hash][extname]'
        },
      },
      onwarn(warning, warn) {
        if (warning.message && warning.message.includes('dynamic import will not move module into another chunk')) {
          return
        }
        warn(warning)
      },
    },
    minify: 'esbuild',
    sourcemap: false,
    cssCodeSplit: true,
    target: 'es2015',
    reportCompressedSize: true,
  }
}
