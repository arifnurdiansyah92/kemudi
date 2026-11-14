import { TriangleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  skillProblem,
  useSetSkillEnabled,
  useSkillLibrary,
  type LibrarySkill,
} from '@/lib/kemudi-ai/skills'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ScanBadge, SourceBadge } from './badges'

/** The enable switch, shared by the list rows and the detail sheet. A high
 * finding blocks enabling (the server refuses it too). */
export function EnableSwitch({
  skill,
  id,
}: {
  skill: Pick<
    LibrarySkill,
    'slug' | 'title' | 'enabled' | 'scan_level' | 'version'
  >
  id?: string
}) {
  const { t } = useTranslation('skills')
  const save = useSetSkillEnabled()
  const blocked =
    !skill.enabled && (skill.scan_level === 'high' || skill.version === null)
  return (
    <Switch
      id={id}
      checked={skill.enabled}
      disabled={blocked || save.isPending}
      aria-label={t('list.enable', { title: skill.title })}
      title={skill.scan_level === 'high' ? t('list.highBlocks') : undefined}
      onCheckedChange={(enabled) =>
        save.mutate(
          { slug: skill.slug, enabled },
          {
            onSuccess: () =>
              toast.success(
                t(enabled ? 'list.enabled' : 'list.disabled', {
                  title: skill.title,
                })
              ),
            onError: (e) => {
              const p = skillProblem(e)
              toast.error(t('list.enableFailed', { title: skill.title }), {
                description: [p.message, ...p.problems].join(' '),
              })
            },
          }
        )
      }
    />
  )
}

export function SkillList({ onOpen }: { onOpen: (slug: string) => void }) {
  const { t } = useTranslation(['skills', 'common'])
  const library = useSkillLibrary()

  if (library.isPending)
    return (
      <div className='grid gap-2' aria-label={t('list.loading')}>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className='h-16 w-full' />
        ))}
      </div>
    )
  if (library.isError)
    return (
      <p role='alert' className='text-sm'>
        {t('list.loadError')}{' '}
        <Button
          variant='link'
          className='h-auto p-0'
          onClick={() => library.refetch()}
        >
          {t('common:actions.retry')}
        </Button>
      </p>
    )
  const skills = library.data.skills
  if (skills.length === 0)
    return (
      <div className='rounded-lg border border-dashed p-10 text-center'>
        <p className='font-medium'>{t('list.emptyTitle')}</p>
        <p className='mt-1 text-sm text-muted-foreground'>
          {t('list.emptyHint')}
        </p>
      </div>
    )

  return (
    <div className='grid gap-2'>
      <p className='text-xs text-muted-foreground'>
        {t('list.count', { count: skills.length })}
      </p>
      <ul className='divide-y rounded-lg border bg-card'>
        {skills.map((s) => (
          <SkillRow key={s.slug} skill={s} onOpen={() => onOpen(s.slug)} />
        ))}
      </ul>
    </div>
  )
}

function SkillRow({
  skill: s,
  onOpen,
}: {
  skill: LibrarySkill
  onOpen: () => void
}) {
  const { t } = useTranslation('skills')
  return (
    <li className='flex items-center gap-3 px-4 py-3'>
      <button
        type='button'
        onClick={onOpen}
        className='grid min-w-0 flex-1 gap-1 rounded-md text-start outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'
      >
        <span className='flex flex-wrap items-baseline gap-x-2 gap-y-0.5'>
          <span className='text-sm font-medium hover:underline hover:underline-offset-4'>
            {s.title}
          </span>
          {s.title !== s.slug && (
            <span className='font-mono text-xs text-muted-foreground'>
              {s.slug}
            </span>
          )}
        </span>
        {s.description && (
          <span className='line-clamp-1 text-xs text-muted-foreground'>
            {s.description}
          </span>
        )}
        <span className='flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground'>
          <SourceBadge source={s.source} />
          {s.version !== null ? (
            <>
              <span className='tabular-nums'>
                {t('list.version', { version: s.version })}
              </span>
              <ScanBadge level={s.scan_level} />
            </>
          ) : (
            <span className='text-destructive'>{t('list.noVersion')}</span>
          )}
          {s.license ? (
            <span>{t('list.license', { license: s.license })}</span>
          ) : (
            <span className='inline-flex items-center gap-1'>
              <TriangleAlert className='size-3.5' aria-hidden />
              {t('list.noLicense')}
            </span>
          )}
          <span>{t('list.usedBy', { count: s.used_by.length })}</span>
          {s.pending_versions > 0 && (
            <span>{t('list.pending', { count: s.pending_versions })}</span>
          )}
        </span>
      </button>
      <EnableSwitch skill={s} />
    </li>
  )
}
