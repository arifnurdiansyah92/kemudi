// Owned by the runner, never by the branch: the agent writes only the spec.
// Every test ends with a full-page screenshot that becomes QA evidence.
const { defineConfig } = require('@playwright/test')

const env = process.env

module.exports = defineConfig({
  testDir: env.QA_SPEC_DIR,
  outputDir: env.QA_OUTPUT_DIR,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['json', { outputFile: env.QA_REPORT }]],
  use: {
    baseURL: env.QA_BASE_URL,
    storageState: env.QA_STATE,
    screenshot: { mode: 'on', fullPage: true },
    viewport: { width: 1440, height: 900 },
    locale: 'en-US',
  },
})
