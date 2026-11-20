import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import jsdoc from 'eslint-plugin-jsdoc';
import globals from 'globals';

const BANNED_LIBRARIES = {
  group: [
    '@mantine/*',
    '@chakra-ui/*',
    'antd',
    'react-bootstrap',
    'bootstrap',
    'styled-components',
    'tailwindcss',
    '@mui/x-*',
  ],
  message: 'Material UI is the only UI library. See CODE_STYLE.md section 6.1.',
};
const BANNED_CSS = {
  group: ['**/*.css', '**/*.scss'],
  message: 'Only src/map/ may import CSS. See CODE_STYLE.md section 6.1.',
};
const BANNED_PATHS = [
  {
    name: '@mui/material',
    message: 'Import from the component path, e.g. @mui/material/Button.',
  },
  {
    name: '@mui/icons-material',
    message: 'Import from the icon path, e.g. @mui/icons-material/Search.',
  },
  {
    name: '@emotion/styled',
    message: 'Use styled from @mui/material/styles.',
  },
];

export default [
  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat['jsx-runtime'],
  jsxA11y.flatConfigs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: { globals: globals.browser },
    settings: { react: { version: 'detect' } },
    plugins: { 'react-hooks': reactHooks, jsdoc },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react/prop-types': 'off',
      'react/forbid-component-props': ['error', { forbid: ['style'] }],
      'react/forbid-dom-props': ['error', { forbid: ['style'] }],
      camelcase: ['error', { properties: 'never' }],
      complexity: ['error', 18],
      'no-var': 'error',
      'prefer-const': 'error',
      eqeqeq: 'error',
      'no-console': 'error',
      'no-restricted-imports': [
        'error',
        { paths: BANNED_PATHS, patterns: [BANNED_LIBRARIES, BANNED_CSS] },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/^#[0-9a-fA-F]{3,8}$/]',
          message: 'Use a theme color token, not a hex literal.',
        },
      ],
      'jsdoc/check-param-names': 'error',
      'jsdoc/check-tag-names': 'error',
      'jsdoc/check-types': 'error',
      'jsdoc/valid-types': 'error',
      'jsdoc/require-returns-check': 'error',
    },
  },
  {
    files: ['src/api/**/*.js'],
    rules: { 'jsdoc/require-jsdoc': ['error', { publicOnly: true }] },
  },
  {
    // The theme file is the one place that defines colors.
    files: ['src/theme/**/*.js'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    // Leaflet needs plain CSS; only the map folder may import it.
    files: ['src/map/**/*.{js,jsx}'],
    rules: {
      'no-restricted-imports': ['error', { paths: BANNED_PATHS, patterns: [BANNED_LIBRARIES] }],
    },
  },
];
