import type { KnipConfig } from 'knip'

const config: KnipConfig = {
  ignore: [
    'src/components/ui/**',
    'src/tanstack-table.d.ts',
    // Table kit kept for the issues list, which is next on the roadmap.
    'src/components/data-table/**',
    'src/test-utils/tanstack-table.ts',
  ],
  // Radix packages behind shadcn ui/ primitives that no screen uses yet.
  ignoreDependencies: [
    '@radix-ui/react-select',
  ],
}

export default config