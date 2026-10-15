#!/usr/bin/env node
/** Compile a self-contained Mod entry before packaging/signing it. */
import { createRequire } from 'node:module'
import { readFile, mkdir } from 'node:fs/promises'
import { dirname, resolve, relative, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'

const fhd = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(resolve(fhd, 'frontend/package.json'))
const { build } = require('esbuild')
const modRoot = resolve(process.argv[2] || '')
if (!process.argv[2]) throw new Error('Usage: node build-runtime-mod-frontend.mjs <mod-root>')
const manifest = JSON.parse(await readFile(resolve(modRoot, 'manifest.json'), 'utf8'))
const runtime = manifest.frontend?.runtime
if (runtime?.sdk_version !== 1) throw new Error('Expected frontend.runtime.sdk_version=1')
function localPath(value, prefix) {
  if (typeof value !== 'string' || !value.startsWith(prefix)) throw new Error(`Expected local ${prefix} path`)
  const path = resolve(modRoot, value)
  const inside = relative(modRoot, path)
  if (inside.startsWith('..') || isAbsolute(inside)) throw new Error('Mod build path escapes source root')
  return path
}
const source = localPath(runtime.source, 'frontend/src/')
const output = localPath(runtime.entry, 'frontend/runtime/')
await mkdir(dirname(output), { recursive: true })
const result = await build({
  entryPoints: [source], outfile: output, bundle: true, format: 'esm',
  platform: 'browser', target: 'es2022', metafile: true, write: false,
})
for (const entry of Object.values(result.metafile.outputs)) {
  if (entry.imports.some((item) => item.external)) throw new Error('Runtime Mod must bundle its dependencies; external imports are forbidden')
}
const { writeFile } = await import('node:fs/promises')
for (const file of result.outputFiles) await writeFile(file.path, file.contents)
process.stdout.write(JSON.stringify({ mod_id: manifest.id, sdk_version: 1, entry: runtime.entry, outputs: result.outputFiles.map((item) => relative(modRoot, item.path)) }) + '\n')
