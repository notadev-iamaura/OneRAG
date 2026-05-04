import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { globalIgnores } from 'eslint/config'

export default tseslint.config([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactRefresh.configs.vite,
    ],
    plugins: {
      'react-hooks': reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // 하드코딩된 색상 사용 금지 - src/config/colors.ts의 COLORS 상수 사용
      'no-restricted-syntax': [
        'error',
        {
          selector: "Literal[value=/#[0-9A-Fa-f]{3,8}/]",
          message: '하드코딩된 hex 색상은 금지됩니다. src/config/colors.ts의 COLORS 또는 getColor()를 사용하세요.'
        },
        {
          selector: "Literal[value=/rgba?\\(/]",
          message: '하드코딩된 rgba/rgb 색상은 금지됩니다. src/config/colors.ts의 COLORS 또는 getColor()를 사용하세요.'
        }
      ]
    }
  },
])
