import { useId, useState } from 'react'
import { formatBytes } from '@/i18n/format'
import { CircleCheck, FileArchive, TriangleAlert, Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  skillProblem,
  useUploadSkill,
  type SkillProblem,
  type UploadResult,
} from '@/lib/kemudi-ai/skills'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FindingList, ScanBadge } from './badges'
import { FindingsRise, RolloutNote } from './rollout'

/** The server's cap on the archive (skills.MAX_UPLOAD_BYTES). */
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024

/**
 * Upload a .zip / .skill / SKILL.md. Shows the server's verdict: the
 * problems that refused it, or the stored version and its scan. A slug that
 * clashes with a local skill offers "Add as new version" (with the roles that
 * get it); a version whose scan is worse than the one roles run now is
 * refused until "Use this version anyway".
 */
export function UploadDialog({
  open,
  onOpenChange,
  onOpenSkill,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpenSkill: (slug: string) => void
}) {
  const { t } = useTranslation('skills')
  const inputId = useId()
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [problem, setProblem] = useState<SkillProblem | null>(null)
  const upload = useUploadSkill()

  const reset = () => {
    setFile(null)
    setResult(null)
    setProblem(null)
    upload.reset()
  }
  const pick = (f: File | undefined) => {
    if (!f) return
    reset()
    setFile(f)
  }
  const send = (replace: boolean, acceptFindings = false) => {
    if (!file) return
    setProblem(null)
    upload.mutate(
      { file, replace, acceptFindings },
      {
        onSuccess: (r) => setResult(r),
        onError: (e) => setProblem(skillProblem(e)),
      }
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('upload.title')}</DialogTitle>
          <DialogDescription>{t('upload.intro')}</DialogDescription>
        </DialogHeader>

        {result ? (
          <UploadOutcome result={result} />
        ) : (
          <div className='grid gap-3'>
            <label
              htmlFor={inputId}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                pick(e.dataTransfer.files[0])
              }}
              className={cn(
                'grid cursor-pointer place-items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center transition-colors hover:bg-muted/40 has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50',
                dragging && 'border-ring bg-muted/40'
              )}
            >
              {file ? (
                <>
                  <FileArchive
                    className='size-6 text-muted-foreground'
                    aria-hidden
                  />
                  <span className='text-sm font-medium break-all'>
                    {file.name}
                  </span>
                  <span className='text-xs text-muted-foreground'>
                    {formatBytes(file.size)} · {t('upload.change')}
                  </span>
                </>
              ) : (
                <>
                  <Upload
                    className='size-6 text-muted-foreground'
                    aria-hidden
                  />
                  <span className='text-sm font-medium'>
                    {t('upload.drop')}
                  </span>
                  <span className='text-xs text-muted-foreground'>
                    {t('upload.dropHint', {
                      size: formatBytes(MAX_UPLOAD_BYTES),
                    })}
                  </span>
                </>
              )}
              <input
                id={inputId}
                type='file'
                accept='.zip,.skill,.md'
                className='sr-only'
                aria-label={t('upload.drop')}
                onChange={(e) => {
                  pick(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>

            {problem && <ProblemView problem={problem} />}
          </div>
        )}

        <DialogFooter>
          {result ? (
            <>
              <Button variant='outline' onClick={() => onOpenChange(false)}>
                {t('upload.close')}
              </Button>
              <Button
                onClick={() => {
                  const slug = result.skill.slug
                  reset()
                  onOpenChange(false)
                  onOpenSkill(slug)
                }}
              >
                {t('upload.open')}
              </Button>
            </>
          ) : problem?.code === 'findings_rise' ? (
            <Button
              variant='destructive'
              disabled={upload.isPending}
              onClick={() => send(true, true)}
            >
              {upload.isPending
                ? t('upload.uploading')
                : t('rollout.useAnyway')}
            </Button>
          ) : problem?.code === 'exists' ? (
            <Button disabled={upload.isPending} onClick={() => send(true)}>
              {upload.isPending
                ? t('upload.uploading')
                : t('upload.addVersion')}
            </Button>
          ) : (
            <Button
              disabled={!file || upload.isPending || !!problem}
              onClick={() => send(false)}
            >
              {upload.isPending ? t('upload.uploading') : t('upload.submit')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProblemView({ problem: p }: { problem: SkillProblem }) {
  const { t } = useTranslation('skills')
  if (p.code === 'exists')
    return (
      <div className='grid gap-1.5 rounded-lg border bg-muted/40 px-3 py-2 text-sm'>
        <p>{t('upload.exists', { slug: p.slug, version: p.version })}</p>
        <RolloutNote
          usedBy={p.used_by?.length ?? 0}
          enabled={p.enabled ?? false}
        />
      </div>
    )
  if (p.code === 'findings_rise') return <FindingsRise problem={p} />
  return (
    <div
      role='alert'
      className='grid gap-1 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive'
    >
      <p className='flex items-center gap-1.5 font-medium'>
        <TriangleAlert className='size-4 shrink-0' aria-hidden />
        {p.code === 'not_local'
          ? t('upload.notLocal', { slug: p.slug })
          : t('upload.refused')}
      </p>
      {p.code !== 'not_local' && (
        <ul className='grid list-disc gap-0.5 ps-5'>
          {(p.problems.length ? p.problems : [p.message]).map((x) => (
            <li key={x} className='break-words'>
              {x}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function UploadOutcome({ result: r }: { result: UploadResult }) {
  const { t } = useTranslation('skills')
  const s = r.skill
  const findings = s.current?.findings ?? []
  const headline = r.unchanged
    ? t('upload.unchanged', { slug: s.slug })
    : r.created
      ? t('upload.created', { slug: s.slug, version: s.version })
      : t('upload.versionAdded', { slug: s.slug, version: s.version })
  return (
    <div className='grid gap-3' role='status'>
      <p className='flex items-start gap-2 text-sm font-medium'>
        <CircleCheck
          className='mt-0.5 size-4 shrink-0 text-success'
          aria-hidden
        />
        {headline}
      </p>
      <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
        <ScanBadge level={s.scan_level} />
        <span>
          {s.license
            ? t('list.license', { license: s.license })
            : t('list.noLicense')}
        </span>
      </div>
      {r.disabled && (
        <p className='text-sm text-destructive'>{t('upload.disabledNow')}</p>
      )}
      {!s.enabled && !r.disabled && (
        <p className='text-sm text-muted-foreground'>
          {t('upload.stillDisabled')}
        </p>
      )}
      {findings.length > 0 && (
        <>
          <p className='text-sm'>
            {t('upload.findings', { count: findings.length })}
          </p>
          <div className='max-h-60 overflow-auto'>
            <FindingList findings={findings} />
          </div>
        </>
      )}
      {r.warnings.map((w) => (
        <p key={w} className='text-xs text-muted-foreground'>
          {w}
        </p>
      ))}
    </div>
  )
}
