import globals from 'globals'
import js from '@eslint/js'
import pluginQuery from '@tanstack/eslint-plugin-query'
import i18next from 'eslint-plugin-i18next'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig } from 'eslint/config'
import tseslint from 'typescript-eslint'

export default defineConfig(
  { ignores: ['dist', 'src/components/ui'] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      ...pluginQuery.configs['flat/recommended'],
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      i18next,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      'no-console': 'error',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          args: 'all',
          argsIgnorePattern: '^_',
          caughtErrors: 'all',
          caughtErrorsIgnorePattern: '^_',
          destructuredArrayIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // Enforce type-only imports for TypeScript types
      '@typescript-eslint/consistent-type-imports': [
        'error',
        {
          prefer: 'type-imports',
          fixStyle: 'inline-type-imports',
          disallowTypeAnnotations: false,
        },
      ],
      // Prevent duplicate imports from the same module
      'no-duplicate-imports': 'error',
      // No hard-coded UI strings: every word a person reads goes through
      // i18next (src/locales). See docs/i18n.md.
      'i18next/no-literal-string': [
        'error',
        {
          mode: 'jsx-only',
          'jsx-attributes': {
            include: [
              'title',
              'placeholder',
              'alt',
              'label',
              'aria-label',
              'aria-description',
              'aria-valuetext',
              'description',
              'heading',
              'message',
              'tooltip',
              'emptyText',
              'confirmText',
              'cancelBtnText',
            ],
          },
          words: {
            exclude: [
              String.raw`^[0-9!-/:-@[-\`{-~\s·•–—…×→←↑↓⌘]+$`,
              '^(Kemudi|Awak|Kemudi Radar|Kemudi Assist)$',
              '^[A-Z]{1,4}$',
            ],
          },
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.object.name='toast'] > :matches(Literal[value=/[A-Za-z]/], TemplateLiteral).arguments:first-child",
          message: 'Toast text must come from i18next: toast.success(t("…")).',
        },
      ],
    },
  },
  {
    // Tests, stories of the UI kit and dev tooling may use literal text.
    files: ['**/*.test.{ts,tsx}', 'src/test-utils/**'],
    rules: {
      'i18next/no-literal-string': 'off',
      'no-restricted-syntax': 'off',
    },
  }
)
