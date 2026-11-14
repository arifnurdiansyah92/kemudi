// Owned by the runner, never by the branch: signs in once through the
// project's login form (the runbook's qa.login) and saves the browser state
// for the spec runs (QA_STATE). The field values come only through QA_LOGIN in
// this process's environment and are never printed.
const { chromium } = require('@playwright/test')

const env = process.env
const cfg = JSON.parse(env.QA_LOGIN)

async function main() {
  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({
      baseURL: env.QA_BASE_URL,
      viewport: { width: 1440, height: 900 },
      locale: 'en-US',
    })
    const page = await context.newPage()
    const loginPath = new URL(cfg.path, env.QA_BASE_URL).pathname
    await page.goto(cfg.path, { timeout: 120_000 })
    for (const f of cfg.fields) {
      await page.locator(f.selector).first().fill(f.value, { timeout: 30_000 })
    }
    await page.locator(cfg.submit).first().click({ timeout: 30_000 })
    const done = (url) =>
      cfg.success_url ? url.pathname.startsWith(cfg.success_url) : url.pathname !== loginPath
    try {
      await page.waitForURL(done, { timeout: 30_000 })
    } catch {
      const where = new URL(page.url()).pathname
      throw new Error(
        `still at ${where} 30 s after submitting the login form` +
          (cfg.success_url ? ` (expected ${cfg.success_url})` : '') +
          '; check the selectors and the vault values of qa.login',
      )
    }
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
    await context.storageState({ path: env.QA_STATE_OUT })
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  // Playwright's messages name selectors, never the typed values.
  console.error('login failed: ' + String((e && e.message) || e).split('\n')[0])
  process.exit(1)
})
