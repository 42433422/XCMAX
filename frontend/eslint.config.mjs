import path from 'node:path'
import { fileURLToPath } from 'node:url'
import js from '@eslint/js'
import { FlatCompat } from '@eslint/eslintrc'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const compat = new FlatCompat({
  baseDirectory: __dirname,
  recommendedConfig: js.configs.recommended,
  allConfig: js.configs.all,
})

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      // Scratch view with legacy mojibake strings; fix encoding before linting again
      'src/views/temp2.vue',
    ],
  },
  ...compat.extends('./.eslintrc.cjs'),
]
