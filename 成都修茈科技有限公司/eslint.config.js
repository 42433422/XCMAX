// 扁平 (Flat) ESLint 9 配置：Vue 3 + TypeScript + Prettier 协作。
// 该文件同时被 MODstore_deploy/market 通过 import 复用，避免两个工作区配置漂移。
import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import vueTsConfig from '@vue/eslint-config-typescript'
import prettierConfig from '@vue/eslint-config-prettier'
import globals from 'globals'

export const ignores = {
  ignores: [
    '**/dist/**',
    '**/node_modules/**',
    '**/coverage/**',
    '**/playwright-report/**',
    '**/test-results/**',
    '**/.trae/**',
    '**/.venv/**',
    '**/__pycache__/**',
    // MODstore_deploy 下的 market 子项目由其自身的 lint 配置（MODstore_deploy/market/eslint.config.js）处理；
    // 根目录 lint 不递归进去，避免把 market 的 venv/打包产物/三方源码全扫一遍。
    'MODstore_deploy/**',
    // 历史打包产物副本与第三方/独立站点目录
    'new/**',
    'public/**',
    'site/**',
    'taiyangniao-pro/**',
    'docker/**',
    'docs/**',
    'deploy/**',
    'alipay_package/**',
    'uploads/**',
    '_local_secrets/**',
    '_nginx_extract/**',
    // 根目录历史 vanilla JS 与各种网页（与 Vue 主仓 src/ 无关，由原静态站维护）
    'main.js',
    'app.py',
    '*.html',
    '**/*.min.js',
    '**/*.min.css',
  ],
}

export const baseRules = {
  files: ['**/*.{js,ts,vue}'],
  rules: {
    'no-console': ['warn', { allow: ['warn', 'error'] }],
    'no-debugger': 'error',
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    '@typescript-eslint/no-explicit-any': 'off',
    // 模板里的 a && b 表达式容易误报；交给后续单独的 lint 收紧 PR 处理。
    '@typescript-eslint/no-unused-expressions': 'off',
    'vue/multi-word-component-names': 'off',
    'vue/no-v-html': 'off',
    // 风格类规则交给 Prettier 处理；ESLint 仅看代码缺陷。
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
  },
}

export const languageOptions = {
  files: ['**/*.{js,ts,vue}'],
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
