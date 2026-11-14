// Owned by the runner, never by the branch: the Setup Assistant's proof that
// a runbook's QA service serves a page. Opens `/` of QA_BASE_URL once (logged
// in when QA_STATE is given, from the runbook's qa.login) and saves a PNG to
// QA_SHOT_OUT.
const { chromium } = require('@playwright/test')

const env = process.env

async function main() {
  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({
      baseURL: env.QA_BASE_URL,
      viewport: { width: 1440, height: 900 },
      locale: 'en-US',
      ...(env.QA_STATE ? { storageState: env.QA_STATE } : {}),
    })
    const page = await context.newPage()
    const res = await page.goto('/', { timeout: 120_000 })
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
    await page.screenshot({ path: env.QA_SHOT_OUT, fullPage: false })
    if (res && res.status() >= 400) {
      throw new Error(`/ answered HTTP ${res.status()} (screenshot saved)`)
    }
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error('screenshot failed: ' + String((e && e.message) || e).split('\n')[0])
  process.exit(1)
})
