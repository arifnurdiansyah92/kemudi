import { useTranslation } from 'react-i18next'
import type {
  Runbook,
  RunbookApp,
  RunbookLogin,
  RunbookOneShot,
  RunbookService,
} from '@/lib/kemudi-ai/agent'
import { Badge } from '@/components/ui/badge'

/** Apps, services and env of a runbook; also shows a proposed one. */
export function RunbookSummary({ runbook: rb }: { runbook: Runbook }) {
  const { t } = useTranslation('agent')
  const apps = Array.isArray(rb.apps) ? rb.apps : []
  const services = Array.isArray(rb.services) ? rb.services : []
  const env = Array.isArray(rb.env) ? rb.env : []
  const init = Array.isArray(rb.init) ? rb.init : []
  // "<service>" or "<service>:<service in its compose file>" → the commands
  // run in that runbook service, labelled with the inner service if named.
  const oneShots = (
    name: string,
    items: (RunbookOneShot | null | undefined)[]
  ) =>
    items
      .filter(
        (o): o is RunbookOneShot => !!o && o.service.split(':')[0] === name
      )
      .map((o) => {
        const inner = o.service.split(':')[1]
        return inner ? `${inner}: ${o.command}` : o.command
      })

  return (
    <div className='grid gap-5'>
      <Group title={t('runbook.apps.title')} count={apps.length}>
        {apps.map((app, i) => (
          <AppRow key={`${app.name}-${i}`} app={app} />
        ))}
      </Group>

      <Group title={t('runbook.services.title')} count={services.length}>
        {services.map((s, i) => (
          <ServiceRow
            key={`${s.name}-${i}`}
            service={s}
            isQa={rb.qa?.service === s.name}
            qaEnv={rb.qa?.service === s.name ? (rb.qa.env ?? []) : []}
            login={rb.qa?.service === s.name ? (rb.qa.login ?? null) : null}
            init={oneShots(s.name, init)}
            seed={oneShots(s.name, [rb.seed])}
          />
        ))}
      </Group>

      <Group title={t('runbook.env.title')} count={env.length}>
        {env.map((e, i) => (
          <li
            key={`${e.name}-${i}`}
            className='grid gap-0.5 px-3 py-2 sm:grid-cols-[minmax(10rem,auto)_minmax(0,1fr)] sm:gap-4'
          >
            <span className='flex flex-wrap items-center gap-2'>
              <code className='font-mono text-xs font-medium'>{e.name}</code>
              {e.secret && (
                <span className='text-xs text-muted-foreground'>
                  {t('runbook.env.secret')}
                </span>
              )}
              {e.required && (
                <span className='text-xs text-muted-foreground'>
                  {t('runbook.env.required')}
                </span>
              )}
            </span>
            {e.description && (
              <span className='text-xs text-muted-foreground'>
                {e.description}
              </span>
            )}
          </li>
        ))}
      </Group>
    </div>
  )
}

function Group({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  const { t } = useTranslation('agent')
  return (
    <section className='grid gap-2'>
      <h3 className='text-sm font-semibold'>
        {title}{' '}
        <span className='font-normal text-muted-foreground tabular-nums'>
          {count}
        </span>
      </h3>
      {count === 0 ? (
        <p className='text-sm text-muted-foreground'>{t('runbook.none')}</p>
      ) : (
        <ul className='divide-y rounded-lg border text-sm'>{children}</ul>
      )}
    </section>
  )
}

/** One label and its command lines, e.g. "Checks" → tsc, lint. */
function Commands({
  rows,
}: {
  rows: [label: string, lines: string[] | undefined][]
}) {
  const shown = rows.filter(([, lines]) => lines && lines.length > 0)
  if (!shown.length) return null
  return (
    <dl className='grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[6rem_minmax(0,1fr)]'>
      {shown.map(([label, lines]) => (
        <div key={label} className='contents'>
          <dt className='text-muted-foreground'>{label}</dt>
          <dd className='grid min-w-0 gap-0.5'>
            {lines!.map((line, i) => (
              <code key={i} className='font-mono break-all'>
                {line}
              </code>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function AppRow({ app }: { app: RunbookApp }) {
  const { t } = useTranslation('agent')
  const envNames = Object.keys(app.env ?? {})
  const hasCommands = [app.install, app.checks, app.build, app.generated].some(
    (c) => Array.isArray(c) && c.length > 0
  )
  return (
    <li className='grid gap-2 px-3 py-2.5'>
      <div className='flex flex-wrap items-baseline gap-x-3 gap-y-1'>
        <span className='font-medium'>{app.name}</span>
        <span className='font-mono text-xs text-muted-foreground'>
          {app.repo}
          {' / '}
          {app.dir || t('runbook.apps.root')}
        </span>
        {app.run_in && (
          <Badge variant='outline' className='font-normal'>
            {t('runbook.apps.runIn', { target: app.run_in })}
          </Badge>
        )}
      </div>
      {hasCommands ? (
        <Commands
          rows={[
            [t('runbook.apps.install'), app.install],
            [t('runbook.apps.checks'), app.checks],
            [t('runbook.apps.build'), app.build],
            [t('runbook.apps.env'), envNames],
            [
              t('runbook.apps.generated'),
              Array.isArray(app.generated) ? app.generated : [],
            ],
          ]}
        />
      ) : (
        <p className='text-xs text-muted-foreground'>
          {t('runbook.apps.noCommands')}
        </p>
      )}
    </li>
  )
}

function ServiceRow({
  service: s,
  isQa,
  qaEnv,
  login,
  init,
  seed,
}: {
  service: RunbookService
  isQa: boolean
  qaEnv: string[]
  login: RunbookLogin | null
  init: string[]
  seed: string[]
}) {
  const { t } = useTranslation('agent')
  const envNames = Array.isArray(s.env) ? s.env : Object.keys(s.env ?? {})
  const source =
    s.kind === 'compose'
      ? [
          [s.repo, s.file].filter(Boolean).join(' / '),
          s.compose_services?.join(', '),
        ]
          .filter(Boolean)
          .join(' · ')
      : s.app
        ? t('runbook.services.ofApp', { app: s.app })
        : ''
  return (
    <li className='grid gap-2 px-3 py-2.5'>
      <div className='flex flex-wrap items-baseline gap-x-3 gap-y-1'>
        <span className='font-medium'>{s.name}</span>
        <Badge variant='secondary' className='font-normal'>
          {s.kind === 'process'
            ? t('runbook.services.kinds.process')
            : s.kind === 'compose'
              ? t('runbook.services.kinds.compose')
              : s.kind}
        </Badge>
        {isQa && (
          <Badge variant='outline' className='font-normal'>
            {t('runbook.services.qaTarget')}
          </Badge>
        )}
        {source && (
          <span className='font-mono text-xs text-muted-foreground'>
            {source}
          </span>
        )}
      </div>
      <Commands
        rows={[
          [t('runbook.services.command'), s.command ? [s.command] : []],
          [t('runbook.services.expose'), s.expose ? [s.expose] : []],
          [
            t('runbook.services.health'),
            [
              t('runbook.services.healthWithin', {
                path: s.health ?? '/',
                seconds: s.ready_timeout ?? 120,
              }),
            ],
          ],
          [t('runbook.services.init'), init],
          [t('runbook.services.seed'), seed],
          [t('runbook.apps.env'), envNames],
          [
            t('runbook.services.login'),
            login
              ? [
                  login.success_url
                    ? t('runbook.services.loginTo', {
                        path: login.path,
                        to: login.success_url,
                      })
                    : login.path,
                ]
              : [],
          ],
          [t('runbook.services.qaEnv'), qaEnv],
        ]}
      />
    </li>
  )
}
