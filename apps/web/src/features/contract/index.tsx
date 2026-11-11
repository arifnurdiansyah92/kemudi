import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useBacktest,
  useContract,
  useSetVerdict,
  useStartBacktest,
  type ContractState,
} from '@/lib/kemudi-ai/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from '@/features/project/use-project'
import { BacktestReport } from './backtest-report'
import { BaselineReview } from './baseline-review'
import { ContractUpload } from './contract-upload'

type Tab = 'contract' | 'baseline' | 'backtest'

export function Contract() {
  const { t } = useTranslation('contract')
  const project = useProject()
  const state = useContract(project.slug)
  const [tab, setTab] = useState<Tab | null>(null)
  // Open where the work is: upload, then review the baseline, then test it.
  const current: Tab =
    tab ??
    (!state.data?.contract
      ? 'contract'
      : state.data.baseline?.approved
        ? 'backtest'
        : 'baseline')

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('title') },
        ]}
      />
      <Main width='table'>
        <h1 className='text-2xl font-semibold tracking-tight'>{t('title')}</h1>
        <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
          {t('intro')}
        </p>
        {state.isPending ? (
          <Skeleton className='mt-8 h-40' />
        ) : state.isError ? (
          <p role='alert' className='mt-8 text-sm text-destructive'>
            {t('unavailable')}
          </p>
        ) : (
          <Tabs
            value={current}
            onValueChange={(v) => setTab(v as Tab)}
            className='mt-6'
          >
            <TabsList>
              <TabsTrigger value='contract'>{t('tabs.contract')}</TabsTrigger>
              <TabsTrigger value='baseline'>{t('tabs.baseline')}</TabsTrigger>
              <TabsTrigger value='backtest'>{t('tabs.backtest')}</TabsTrigger>
            </TabsList>
            <TabsContent value='contract' className='mt-6'>
              <ContractUpload
                slug={project.slug}
                state={state.data}
                isAdmin={project.i_am_admin}
              />
            </TabsContent>
            <TabsContent value='baseline' className='mt-6'>
              <BaselineReview
                slug={project.slug}
                state={state.data}
                isAdmin={project.i_am_admin}
              />
            </TabsContent>
            <TabsContent value='backtest' className='mt-6'>
              <BacktestTab
                slug={project.slug}
                state={state.data}
                isAdmin={project.i_am_admin}
              />
            </TabsContent>
          </Tabs>
        )}
      </Main>
    </>
  )
}

function BacktestTab({
  slug,
  state,
  isAdmin,
}: {
  slug: string
  state: ContractState
  isAdmin: boolean
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const start = useStartBacktest(slug)
  const [file, setFile] = useState<File | null>(null)
  const [picked, setPicked] = useState<number | null>(null)
  const runId = picked ?? state.runs[0]?.id ?? null
  const run = useBacktest(slug, runId)
  const verdict = useSetVerdict(slug, runId ?? 0)

  if (!state.baseline?.approved)
    return (
      <p className='text-sm text-muted-foreground'>
        {t('backtest.needsBaseline')}
      </p>
    )

  return (
    <div className='grid gap-8'>
      <p className='max-w-2xl text-sm text-muted-foreground'>
        {t('backtest.description')}
      </p>
      {isAdmin && (
        <form
          className='flex flex-wrap items-end gap-3'
          onSubmit={(e) => {
            e.preventDefault()
            if (file)
              start.mutate(file, {
                onSuccess: (r) => {
                  setPicked(r.run_id)
                  setFile(null)
                },
              })
          }}
        >
          <div className='grid gap-1.5'>
            <Label htmlFor='backtest-dataset'>{t('backtest.dataset')}</Label>
            <Input
              id='backtest-dataset'
              type='file'
              accept='.json,application/json'
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <Button type='submit' disabled={!file || start.isPending}>
            {start.isPending && <Loader2 className='animate-spin' />}
            {t('backtest.start')}
          </Button>
        </form>
      )}

      {state.runs.length > 1 && (
        <div className='grid max-w-md gap-1.5'>
          <Label htmlFor='backtest-run'>{t('backtest.runs')}</Label>
          <select
            id='backtest-run'
            value={runId ?? ''}
            onChange={(e) => setPicked(Number(e.target.value))}
            className='h-9 rounded-md border bg-background px-2 text-sm'
          >
            {state.runs.map((r) => (
              <option key={r.id} value={r.id}>
                {t('backtest.run', {
                  id: r.id,
                  dataset: r.dataset_name,
                  date: format.date(r.started_at, 'dateTime'),
                })}
              </option>
            ))}
          </select>
        </div>
      )}

      {runId === null ? (
        <p className='text-sm text-muted-foreground'>{t('backtest.empty')}</p>
      ) : run.data ? (
        <>
          {!run.data.run.finished_at && (
            <p
              role='status'
              className='flex items-center gap-2 text-sm text-muted-foreground'
            >
              <Loader2 className='size-4 animate-spin' />
              {t('backtest.running', {
                done: run.data.results.length,
                total: '…',
              })}
            </p>
          )}
          {run.data.run.error && (
            <p role='alert' className='text-sm text-destructive'>
              {t('backtest.failed', { error: run.data.run.error })}
            </p>
          )}
          <BacktestReport
            data={run.data}
            canReview={isAdmin}
            onVerdict={(resultId, v) =>
              verdict.mutate({ resultId, verdict: v })
            }
          />
        </>
      ) : (
        <Skeleton className='h-40' />
      )}
    </div>
  )
}
