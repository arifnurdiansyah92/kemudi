import { useState } from 'react'
import { formatBytes, formatDate } from '@/i18n/format'
import { FileText, FilePen, Trash2, TriangleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  skillProblem,
  useDeleteSkill,
  useSkillDetail,
  useSkillFile,
  type SkillDetail as Detail,
  type SkillFileEntry,
} from '@/lib/kemudi-ai/skills'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { FindingList, ScanBadge, SourceBadge } from './badges'
import { Markdown } from './markdown'
import { MarketplaceOrigin } from './marketplace-update'
import { EnableSwitch } from './skill-list'

/** A skill from the library, in a sheet from the right (like the item sheet). */
export function SkillDetailSheet({
  slug,
  onClose,
  onNewVersion,
}: {
  slug: string | null
  onClose: () => void
  onNewVersion: (slug: string) => void
}) {
  const { t } = useTranslation('skills')
  const detail = useSkillDetail(slug)
  return (
    <Sheet open={!!slug} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className='w-full gap-0 overflow-y-auto sm:max-w-2xl'>
        {detail.data ? (
          <DetailBody
            skill={detail.data}
            onDeleted={onClose}
            onNewVersion={() => onNewVersion(detail.data.slug)}
          />
        ) : (
          <SheetHeader>
            <SheetTitle>{slug}</SheetTitle>
            <SheetDescription>
              {detail.isError ? t('detail.loadError') : t('detail.loading')}
            </SheetDescription>
            {detail.isPending && <Skeleton className='mt-4 h-64 w-full' />}
          </SheetHeader>
        )}
      </SheetContent>
    </Sheet>
  )
}

export function DetailBody({
  skill: s,
  onDeleted,
  onNewVersion,
}: {
  skill: Detail
  onDeleted: () => void
  onNewVersion: () => void
}) {
  const { t } = useTranslation('skills')
  const [confirm, setConfirm] = useState(false)
  const del = useDeleteSkill()
  const cur = s.current
  const switchId = `skill-enabled-${s.slug}`

  const remove = () =>
    del.mutate(s.slug, {
      onSuccess: () => {
        toast.success(t('detail.deleted', { title: s.title }))
        setConfirm(false)
        onDeleted()
      },
      onError: (e) => {
        const p = skillProblem(e)
        setConfirm(false)
        toast.error(
          p.code === 'in_use' && p.used_by
            ? t('detail.deleteInUse', {
                roles: p.used_by
                  .map((u) => `${u.project} / ${u.role}`)
                  .join(', '),
              })
            : p.message
        )
      },
    })

  return (
    <>
      <SheetHeader className='gap-2 border-b pe-12'>
        <SheetTitle className='flex flex-wrap items-baseline gap-x-2'>
          {s.title}
          {s.title !== s.slug && (
            <span className='font-mono text-xs font-normal text-muted-foreground'>
              {s.slug}
            </span>
          )}
        </SheetTitle>
        <SheetDescription>{s.description}</SheetDescription>
        <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
          <SourceBadge source={s.source} />
          {s.version !== null && (
            <span className='tabular-nums'>
              {t('list.version', { version: s.version })}
            </span>
          )}
          {s.version !== null && <ScanBadge level={s.scan_level} />}
          <span>
            {s.license
              ? t('list.license', { license: s.license })
              : t('list.noLicense')}
          </span>
        </div>
      </SheetHeader>

      <div className='grid gap-4 p-4'>
        <div className='flex flex-wrap items-center justify-between gap-3'>
          <div className='flex items-center gap-3'>
            <EnableSwitch skill={s} id={switchId} />
            <div className='grid gap-0.5'>
              <Label htmlFor={switchId}>{t('detail.enabled')}</Label>
              <p className='text-xs text-muted-foreground'>
                {s.enabled ? t('detail.enabledHint') : t('detail.disabledHint')}
              </p>
            </div>
          </div>
          <div className='flex flex-wrap gap-2'>
            {s.source === 'local' && (
              <Button size='sm' variant='outline' onClick={onNewVersion}>
                <FilePen />
                {t('detail.newVersion')}
              </Button>
            )}
            {s.source !== 'builtin' && (
              <Button
                size='sm'
                variant='ghost'
                className='text-destructive hover:text-destructive'
                onClick={() => setConfirm(true)}
              >
                <Trash2 />
                {t('detail.delete')}
              </Button>
            )}
          </div>
        </div>

        {!s.license && <Notice>{t('detail.noLicenseWarning')}</Notice>}
        {s.scan_level === 'high' && (
          <Notice danger>{t('detail.highWarning')}</Notice>
        )}
        {s.source === 'marketplace' && <MarketplaceOrigin skill={s} />}

        {cur ? (
          <Tabs defaultValue='skill-md'>
            <TabsList className='h-auto flex-wrap'>
              <TabsTrigger value='skill-md'>
                {t('detail.tabs.skillMd')}
              </TabsTrigger>
              <TabsTrigger value='files'>
                {t('detail.tabs.files')}
                <Count n={cur.files.length} />
              </TabsTrigger>
              <TabsTrigger value='findings'>
                {t('detail.tabs.findings')}
                <Count n={cur.findings.length} />
              </TabsTrigger>
              <TabsTrigger value='versions'>
                {t('detail.tabs.versions')}
                <Count n={s.versions.length} />
              </TabsTrigger>
              <TabsTrigger value='used-by'>
                {t('detail.tabs.usedBy')}
                <Count n={s.used_by.length} />
              </TabsTrigger>
            </TabsList>

            <TabsContent value='skill-md' className='grid gap-4 pt-2'>
              <Markdown source={cur.skill_md} />
              {cur.license_files.length > 0 && (
                <section className='grid gap-2'>
                  <h3 className='text-sm font-medium'>
                    {t('detail.licenseFiles')}
                  </h3>
                  {cur.license_files.map((f) => (
                    <div key={f.path} className='grid gap-1'>
                      <p className='font-mono text-xs text-muted-foreground'>
                        {f.path}
                      </p>
                      <pre className='max-h-48 overflow-auto rounded-lg border bg-muted/40 px-3 py-2 font-mono text-xs whitespace-pre-wrap'>
                        {f.text}
                      </pre>
                    </div>
                  ))}
                </section>
              )}
            </TabsContent>

            <TabsContent value='files' className='pt-2'>
              <FileBrowser
                slug={s.slug}
                sha={cur.sha256}
                version={cur.version}
                files={cur.files}
              />
            </TabsContent>

            <TabsContent value='findings' className='grid gap-3 pt-2'>
              {cur.findings.length ? (
                <FindingList findings={cur.findings} />
              ) : (
                <p className='text-sm text-muted-foreground'>
                  {t('detail.noFindings')}
                </p>
              )}
              {cur.warnings.length > 0 && (
                <section className='grid gap-1'>
                  <h3 className='text-sm font-medium'>
                    {t('detail.warnings')}
                  </h3>
                  <ul className='list-disc ps-5 text-sm text-muted-foreground'>
                    {cur.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </section>
              )}
            </TabsContent>

            <TabsContent value='versions' className='pt-2'>
              <ul className='divide-y rounded-lg border'>
                {s.versions.map((v) => (
                  <li
                    key={v.version}
                    className='flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm'
                  >
                    <span className='w-10 font-medium tabular-nums'>
                      {t('list.version', { version: v.version })}
                    </span>
                    {v.version === s.version && (
                      <Badge variant='secondary' className='font-normal'>
                        {t('detail.current')}
                      </Badge>
                    )}
                    {v.status === 'pending' && (
                      <Badge variant='outline' className='font-normal'>
                        {t('detail.pending')}
                      </Badge>
                    )}
                    <ScanBadge level={v.scan_level} />
                    <span className='text-xs text-muted-foreground'>
                      {t('detail.versionBy', {
                        who: v.created_by,
                        when: formatDate(v.created_at),
                      })}
                    </span>
                    <span className='ms-auto text-xs text-muted-foreground tabular-nums'>
                      {t('detail.filesCount', { count: v.files })} ·{' '}
                      {formatBytes(v.size)} ·{' '}
                      <span className='font-mono' title={v.sha256}>
                        {v.sha256.slice(0, 12)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </TabsContent>

            <TabsContent value='used-by' className='pt-2'>
              {s.used_by.length ? (
                <ul className='divide-y rounded-lg border'>
                  {s.used_by.map((u) => (
                    <li key={u.role_id} className='px-3 py-2 text-sm'>
                      <span className='text-muted-foreground'>{u.project}</span>
                      {' / '}
                      <span className='font-medium'>{u.role}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className='text-sm text-muted-foreground'>
                  {t('detail.notUsed')}
                </p>
              )}
            </TabsContent>
          </Tabs>
        ) : (
          <p className='text-sm text-muted-foreground'>
            {t('detail.noCurrent')}
          </p>
        )}
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t('detail.deleteTitle', { title: s.title })}
        desc={t('detail.deleteBody')}
        confirmText={t('detail.delete')}
        destructive
        isLoading={del.isPending}
        handleConfirm={remove}
      />
    </>
  )
}

function Count({ n }: { n: number }) {
  return <span className='text-xs text-muted-foreground tabular-nums'>{n}</span>
}

function Notice({
  children,
  danger,
}: {
  children: React.ReactNode
  danger?: boolean
}) {
  return (
    <p
      className={cn(
        'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
        danger
          ? 'border-destructive/30 bg-destructive/5 text-destructive'
          : 'bg-muted/40'
      )}
    >
      <TriangleAlert className='mt-0.5 size-4 shrink-0' aria-hidden />
      {children}
    </p>
  )
}

function FileBrowser({
  slug,
  sha,
  version,
  files,
}: {
  slug: string
  sha: string
  version: number
  files: SkillFileEntry[]
}) {
  const { t } = useTranslation('skills')
  const [path, setPath] = useState<string | null>(null)
  const picked = files.find((f) => f.path === path) ?? null
  const file = useSkillFile(
    slug,
    sha,
    version,
    picked && !picked.binary ? picked.path : null
  )

  return (
    <div className='grid gap-3'>
      <ul
        className='divide-y rounded-lg border'
        aria-label={t('detail.tabs.files')}
      >
        {files.map((f) => (
          <li key={f.path}>
            <button
              type='button'
              onClick={() => setPath(f.path)}
              aria-current={f.path === path ? 'true' : undefined}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-start text-sm outline-none hover:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/50',
                f.path === path && 'bg-muted font-medium'
              )}
            >
              <FileText
                className='size-4 shrink-0 text-muted-foreground'
                aria-hidden
              />
              <span className='min-w-0 flex-1 truncate font-mono text-xs'>
                {f.path}
              </span>
              <span className='text-xs text-muted-foreground tabular-nums'>
                {formatBytes(f.size)}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {!picked ? (
        <p className='text-sm text-muted-foreground'>{t('detail.pickFile')}</p>
      ) : picked.binary ? (
        <p className='text-sm text-muted-foreground'>
          {t('detail.binary', { size: formatBytes(picked.size) })}
        </p>
      ) : file.isError ? (
        <p role='alert' className='text-sm text-destructive'>
          {t('detail.fileError')}
        </p>
      ) : file.data?.text !== undefined ? (
        <pre
          aria-label={picked.path}
          className='max-h-[28rem] overflow-auto rounded-lg border bg-muted/40 px-3 py-2 font-mono text-xs whitespace-pre-wrap'
        >
          {file.data.text}
        </pre>
      ) : (
        <Skeleton className='h-40 w-full' />
      )}
    </div>
  )
}
