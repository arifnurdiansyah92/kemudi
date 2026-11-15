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
    // Why a submit did not land: each non-GET request's status (never its
    // body or the typed values) and the page's alert text, for the message.
    const posts = []
    page.on('response', (r) => {
      const req = r.request()
      if (req.method() !== 'GET' && ['xhr', 'fetch', 'document'].includes(req.resourceType())) {
        posts.push(`${req.method()} ${new URL(r.url()).pathname} -> ${r.status()}`)
      }
    })
    const loginPath = new URL(cfg.path, env.QA_BASE_URL).pathname
    const done = (url) =>
      cfg.success_url ? url.pathname.startsWith(cfg.success_url) : url.pathname !== loginPath
    // Filling or clicking before the page hydrates loses the typed values and
    // lets the browser submit the bare <form> natively (back to the login
    // page), so wait for the page to settle, and on a miss reload and retry.
    // A dev server also compiles the page the login lands on at its first
    // visit; on a busy machine that alone can take more than 30 s.
    const waits = [45_000, 35_000, 25_000]
    let landed = false
    for (let i = 0; i < waits.length && !landed; i++) {
      await page.goto(cfg.path, { timeout: 120_000 })
      await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
      if (done(new URL(page.url()))) {
        landed = true // an earlier attempt signed in after all
        break
      }
      for (const f of cfg.fields) {
        await page.locator(f.selector).first().fill(f.value, { timeout: 30_000 })
      }
      await page.locator(cfg.submit).first().click({ timeout: 30_000 })
      landed = await page.waitForURL(done, { timeout: waits[i] }).then(() => true, () => false)
    }
    if (!landed) {
      const where = new URL(page.url()).pathname
      const alert = await page
        .locator('[role=alert]')
        .allInnerTexts()
        .then((t) => t.join(' | ').replace(/\s+/g, ' ').slice(0, 200), () => '')
      throw new Error(
        `still at ${where} after ${waits.length} login attempts` +
          (cfg.success_url ? ` (expected ${cfg.success_url})` : '') +
          `; requests: ${posts.slice(-6).join(', ') || 'none sent'}` +
          (alert ? `; page says: ${alert}` : '') +
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
