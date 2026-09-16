// Convex's official plugin. If their own linter passes on this code, "idiomatic" stops
// being our opinion. https://docs.convex.dev/eslint
import convexPlugin from '@convex-dev/eslint-plugin';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['convex/_generated/**'] },
  {
    files: ['convex/**/*.ts'],
    languageOptions: {
      parser: tseslint.parser,
      // explicit-table-ids needs type information to autofix and to avoid false positives.
      parserOptions: { project: './tsconfig.json', tsconfigRootDir: import.meta.dirname },
    },
  },
  ...convexPlugin.configs.recommended,
  {
    files: ['convex/**/*.ts'],
    rules: {
      // Not in `recommended`, and the one that actually catches unbounded reads.
      '@convex-dev/no-collect-in-query': 'warn',
    },
  },
);
