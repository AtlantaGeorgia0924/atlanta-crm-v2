import tsParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'

const browserGlobals = {
  console: 'readonly',
  document: 'readonly',
  window: 'readonly',
  localStorage: 'readonly',
  setInterval: 'readonly',
  clearInterval: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  URLSearchParams: 'readonly',
  FormData: 'readonly',
  FileReader: 'readonly',
  Blob: 'readonly',
}

export default [
  {
    ignores: ['dist/**', 'node_modules/**'],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2020,
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: browserGlobals,
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
]
