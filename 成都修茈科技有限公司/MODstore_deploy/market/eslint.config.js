// MODstore_deploy/market 子项目独立 ESLint 9 扁平配置。
// 配置内容与根目录 eslint.config.js 保持一致；两个工作区各自从自己的 node_modules 解析依赖，
// 因此采用副本而非 import 跨工作区文件，避免 monorepo 解析问题。
import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import vueTsConfig from '@vue/eslint-config-typescript'
import prettierConfig from '@vue/eslint-config-prettier'
import globals from 'globals'

const ignores = {
  ignores: [
    '**/dist/**',
    '**/node_modules/**',
    '**/coverage/**',
    '**/playwright-report/**',
    '**/test-results/**',
    '**/.venv/**',
    '**/__pycache__/**',
    '**/*.min.js',
    '**/*.min.css',
    'public/**',
    'src/views/_fix_refs.cjs',
  ],
}

const baseRules = {
  files: ['**/*.{cjs,js,mjs,ts,tsx,vue}'],
  rules: {
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'no-debugger': 'error',
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    '@typescript-eslint/no-explicit-any': 'warn',
    '@typescript-eslint/no-unused-expressions': 'off',
    '@typescript-eslint/no-this-alias': 'warn',
    '@typescript-eslint/no-unnecessary-type-constraint': 'warn',
    '@typescript-eslint/no-unsafe-function-type': 'warn',
    'vue/multi-word-component-names': 'off',
    'vue/no-v-html': 'off',
    'prettier/prettier': 'off',
    'vue/component-tags-order': 'off',
    'vue/attributes-order': 'off',
    'vue/block-lang': 'off',
    'vue/v-on-event-hyphenation': 'off',
    'vue/first-attribute-linebreak': 'off',
    'vue/no-template-shadow': 'off',
    // 历史代码中存在少量空 catch / 模板转义；先降为 warning，后续清理 PR 中再收紧。
    'no-empty': 'warn',
    'no-useless-escape': 'warn',
    'prefer-const': 'warn',
  },
}

const languageOptions = {
  files: ['**/*.{cjs,js,mjs,ts,tsx,vue}'],
  languageOptions: {
    globals: {
      ...globals.browser,
      ...globals.node,
      ...globals.es2022,
    },
  },
}

export default [
  ignores,
  js.configs.recommended,
  ...vue.configs['flat/recommended'],
  ...vueTsConfig(),
  prettierConfig,
  languageOptions,
  baseRules,
]
