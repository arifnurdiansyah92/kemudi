import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { AgentUsage } from '@/lib/kemudi-ai/usage'
import { UsageBudget } from './usage-budget'

const base: AgentUsage = {
  month_start: '2026-11-01T00:00:00',
  calls: 40,
  prompt_tokens: 4_400_000,
  cached_tokens: 2_000_000,
  completion_tokens: 100_000,
  tokens: 4_500_000,
  cost_idr: 12_500,
  unknown_cost_calls: 0,
  unreported_calls: 0,
  setup_tokens: 1_500_000,
  setup_cost_idr: 3_000,
  budget: {
    monthly_tokens: null,
    story_cap: null,
    used_ratio: null,
    warning: false,
    exceeded: false,
    recommended_monthly_tokens: 50_000_000,
  },
  price: {
    model: 'deepseek-flash',
    source: 'table',
    input: 0.14,
    cached_input: 0.028,
    output: 0.28,
    currency: 'USD',
  },
  price_override: null,
  usd_idr_rate: 16500,
  stories: [
    {
      job_id: 3,
      story_ref: 12,
      state: 'passed',
      calls: 8,
      prompt_tokens: 2_150_000,
      completion_tokens: 50_000,
      tokens: 2_200_000,
      cost_idr: 6_000,
      cost_unknown: false,
      updated_at: '2026-11-14T01:00:00Z',
    },
  ],
}

const withBudget = (used: number, budget: number): AgentUsage => ({
  ...base,
  tokens: used,
  budget: {
    ...base.budget,
    monthly_tokens: budget,
    used_ratio: used / budget,
    warning: used >= 0.8 * budget,
    exceeded: used >= budget,
  },
})

describe('UsageBudget', () => {
  it('shows this month, the recent stories and a recommendation without a budget', async () => {
    const screen = await render(
      <UsageBudget usage={base} canEdit pending={false} onSave={vi.fn()} />
    )
    await expect.element(screen.getByText('4.5 M')).toBeVisible()
    await expect.element(screen.getByText('Rp12,500')).toBeVisible()
    await expect.element(screen.getByText('#12')).toBeVisible()
    await expect.element(screen.getByText('2,200,000')).toBeVisible()
    await expect
      .element(screen.getByText(/We recommend starting at 50 M tokens a month/))
      .toBeVisible()
    await expect
      .element(screen.getByText(/\$0\.14 input and \$0\.28 output/))
      .toBeVisible()
  })

  it('warns from 80% of the budget', async () => {
    const screen = await render(
      <UsageBudget
        usage={withBudget(41_000_000, 50_000_000)}
        canEdit
        pending={false}
        onSave={vi.fn()}
      />
    )
    await expect
      .element(screen.getByText("82% of this month's token budget used"))
      .toBeVisible()
    await expect.element(screen.getByText('41 M of 50 M')).toBeVisible()
    await expect
      .element(screen.getByRole('progressbar'))
      .toHaveAttribute('aria-valuenow', '82')
  })

  it('says Awak stopped once the budget is used up', async () => {
    const screen = await render(
      <UsageBudget
        usage={withBudget(50_000_000, 50_000_000)}
        canEdit={false}
        pending={false}
        onSave={vi.fn()}
      />
    )
    await expect
      .element(screen.getByText('Monthly token budget used up'))
      .toBeVisible()
    await expect
      .element(screen.getByText('Only project admins can change the budget.'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Save budget' }))
      .not.toBeInTheDocument()
  })

  it('shows an unknown price as unknown, never as zero', async () => {
    const screen = await render(
      <UsageBudget
        usage={{
          ...base,
          unknown_cost_calls: 3,
          price: {
            model: 'my-finetune',
            source: null,
            input: null,
            cached_input: null,
            output: null,
            currency: null,
          },
          stories: [{ ...base.stories[0], cost_idr: 0, cost_unknown: true }],
        }}
        canEdit
        pending={false}
        onSave={vi.fn()}
      />
    )
    await expect
      .element(screen.getByText(/There's no price for my-finetune/))
      .toBeVisible()
    await expect
      .element(screen.getByText('Plus 3 calls with an unknown price'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('cell', { name: 'Unknown' }))
      .toBeVisible()
  })

  it('saves the budget in tokens and the price override', async () => {
    const onSave = vi.fn()
    const screen = await render(
      <UsageBudget usage={base} canEdit pending={false} onSave={onSave} />
    )
    await screen
      .getByLabelText('Monthly token budget (million tokens)')
      .fill('40')
    await screen
      .getByLabelText('Token cap per story (million tokens)')
      .fill('2.5')
    await screen.getByLabelText("Set this project's model price").click()
    await screen.getByLabelText('Input per 1M', { exact: true }).fill('0.3')
    await screen.getByLabelText('Output per 1M').fill('0.5')
    await screen.getByRole('button', { name: 'Save budget' }).click()
    expect(onSave).toHaveBeenCalledWith({
      monthly_tokens: 40_000_000,
      story_cap: 2_500_000,
      price: { input: 0.3, cached_input: null, output: 0.5, currency: 'USD' },
    })
  })

  it('refuses a budget that is not a number', async () => {
    const onSave = vi.fn()
    const screen = await render(
      <UsageBudget usage={base} canEdit pending={false} onSave={onSave} />
    )
    await screen
      .getByLabelText('Monthly token budget (million tokens)')
      .fill('lots')
    await screen.getByRole('button', { name: 'Save budget' }).click()
    expect(onSave).not.toHaveBeenCalled()
    await expect
      .element(screen.getByText(/Enter the budget and cap as a number/))
      .toBeVisible()
  })
})
