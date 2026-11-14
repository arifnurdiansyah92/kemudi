import { useEffect, useId, useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { formatBytes } from '@/i18n/format'
import { CircleCheck, LoaderCircle, Plus, TriangleAlert, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  filePath,
  skillProblem,
  useCheckDraft,
  useSaveSkill,
  useSkillDetail,
  type SkillDetail,
  type SkillDraft,
  type SkillFile,
} from '@/lib/kemudi-ai/skills'
import { api } from '@/lib/taiga/client'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { FindingList } from './badges'
import { initialFrom, type EditorInitial } from './editor-initial'
import { Markdown } from './markdown'

/** The server's limits (kemudi_ai/awak/skills.py). */
const DESCRIPTION_MAX = 1024
const DESCRIPTION_AGENT_MAX = 300
const CHECK_DELAY_MS = 400

type FileRow = { id: number; path: string; text: string }

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

const EMPTY: EditorInitial = {
  slug: '',
  description: '',
  license: '',
  body: '',
  files: [],
}

/**
 * Write a skill (or the next version of a local one): the fields Kemudi
 * builds SKILL.md from, a debounced server check (validation + scan), and a
 * preview of the SKILL.md as Awak gets it.
 */
export function SkillEditor({
  initial = EMPTY,
  existing,
  onSaved,
  onCancel,
}: {
  initial?: EditorInitial
  /** Set for a new version of this skill. */
  existing?: SkillDetail
  onSaved: (slug: string) => void
  onCancel?: () => void
}) {
  const { t } = useTranslation('skills')
  const ids = useId()
  const [slug, setSlug] = useState(initial.slug)
  const [description, setDescription] = useState(initial.description)
  const [license, setLicense] = useState(initial.license)
  const [body, setBody] = useState(initial.body)
  const [files, setFiles] = useState<FileRow[]>(() =>
    initial.files.map((f, i) => ({ id: i, ...f }))
  )
  const [nextId, setNextId] = useState(initial.files.length)
  const [saveProblems, setSaveProblems] = useState<string[]>([])
  const save = useSaveSkill()

  const duplicate = useMemo(() => {
    const seen = new Set<string>()
    for (const f of files) {
      if (seen.has(f.path)) return f.path
      seen.add(f.path)
    }
    return null
  }, [files])

  const draft: SkillDraft = useMemo(
    () => ({
      slug: slug.trim(),
      description,
      body,
      license: license.trim(),
      files: Object.fromEntries(files.map((f) => [f.path, f.text])),
    }),
    [slug, description, body, license, files]
  )
  const debounced = useDebounced(draft, CHECK_DELAY_MS)
  const filled = !!(debounced.slug && debounced.description.trim())
  const check = useCheckDraft(filled ? debounced : null)
  const fresh = debounced === draft && !check.isFetching && !!check.data
  const blocked = fresh && !check.data!.ok

  const binaries = existing?.current?.files.filter((f) => f.binary).length ?? 0
  const descCount = description.trim().length

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSaveProblems([])
    save.mutate(
      { draft, existing: !!existing },
      {
        onSuccess: (d) => {
          const unchanged = 'unchanged' in d && d.unchanged
          if (unchanged) toast.info(t('editor.unchanged'))
          else toast.success(t('editor.saved', { slug: d.slug }))
          onSaved(d.slug)
        },
        onError: (err) => {
          const p = skillProblem(err)
          setSaveProblems(p.problems.length ? p.problems : [p.message])
        },
      }
    )
  }

  return (
    <form
      onSubmit={submit}
      className='grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]'
    >
      <div className='grid gap-5'>
        <div className='grid gap-1'>
          <h2 className='text-base font-semibold'>
            {existing
              ? t('editor.versionTitle', { slug: existing.slug })
              : t('editor.newTitle')}
          </h2>
          <p className='text-sm text-muted-foreground'>
            {existing
              ? t('editor.versionIntro', {
                  next: (existing.versions[0]?.version ?? 0) + 1,
                })
              : t('editor.newIntro')}
            {binaries > 0 &&
              ` ${t('editor.keepsBinaries', { count: binaries })}`}
          </p>
        </div>

        <div className='grid gap-1.5'>
          <Label htmlFor={`${ids}-slug`}>{t('editor.slug')}</Label>
          <Input
            id={`${ids}-slug`}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={!!existing}
            maxLength={64}
            autoComplete='off'
            spellCheck={false}
            className='font-mono'
            aria-describedby={`${ids}-slug-hint`}
          />
          <p id={`${ids}-slug-hint`} className='text-xs text-muted-foreground'>
            {t('editor.slugHint')}
          </p>
        </div>

        <div className='grid gap-1.5'>
          <div className='flex items-baseline justify-between gap-3'>
            <Label htmlFor={`${ids}-desc`}>{t('editor.description')}</Label>
            <span
              className={cn(
                'text-xs tabular-nums',
                descCount > DESCRIPTION_MAX
                  ? 'text-destructive'
                  : 'text-muted-foreground'
              )}
            >
              {t('editor.descriptionCount', {
                used: descCount,
                max: DESCRIPTION_MAX,
              })}
            </span>
          </div>
          <Textarea
            id={`${ids}-desc`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            aria-describedby={`${ids}-desc-hint`}
            aria-invalid={descCount > DESCRIPTION_MAX || undefined}
          />
          <p id={`${ids}-desc-hint`} className='text-xs text-muted-foreground'>
            {t('editor.descriptionHint')}
            {descCount > DESCRIPTION_AGENT_MAX &&
              ` ${t('editor.descriptionCut', { max: DESCRIPTION_AGENT_MAX })}`}
          </p>
        </div>

        <div className='grid gap-1.5 sm:max-w-xs'>
          <Label htmlFor={`${ids}-license`}>{t('editor.license')}</Label>
          <Input
            id={`${ids}-license`}
            value={license}
            onChange={(e) => setLicense(e.target.value)}
            maxLength={100}
            placeholder={t('editor.licensePlaceholder')}
          />
        </div>

        <div className='grid gap-1.5'>
          <Label htmlFor={`${ids}-body`}>{t('editor.body')}</Label>
          <Textarea
            id={`${ids}-body`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={16}
            spellCheck={false}
            className='font-mono text-xs leading-relaxed'
            aria-describedby={`${ids}-body-hint`}
          />
          <p id={`${ids}-body-hint`} className='text-xs text-muted-foreground'>
            {t('editor.bodyHint')}
          </p>
        </div>

        <section className='grid gap-3' aria-labelledby={`${ids}-files`}>
          <h3 id={`${ids}-files`} className='-mb-2 text-sm font-medium'>
            {t('editor.files')}
          </h3>
          <p className='text-xs text-muted-foreground'>
            {t('editor.filesHint')}
          </p>
          {files.map((f) => (
            <div key={f.id} className='grid gap-2 rounded-lg border p-3'>
              <div className='flex items-center gap-2'>
                <Input
                  value={f.path}
                  aria-label={t('editor.filePath')}
                  placeholder='reference/notes.md'
                  spellCheck={false}
                  className='h-8 font-mono text-xs'
                  onChange={(e) =>
                    setFiles((xs) =>
                      xs.map((x) =>
                        x.id === f.id ? { ...x, path: e.target.value } : x
                      )
                    )
                  }
                />
                <Button
                  type='button'
                  size='icon'
                  variant='ghost'
                  className='size-8 shrink-0 text-muted-foreground'
                  aria-label={t('editor.removeFile', {
                    path: f.path || t('editor.untitled'),
                  })}
                  onClick={() =>
                    setFiles((xs) => xs.filter((x) => x.id !== f.id))
                  }
                >
                  <X />
                </Button>
              </div>
              <Textarea
                value={f.text}
                aria-label={t('editor.fileText', {
                  path: f.path || t('editor.untitled'),
                })}
                rows={6}
                spellCheck={false}
                className='font-mono text-xs'
                onChange={(e) =>
                  setFiles((xs) =>
                    xs.map((x) =>
                      x.id === f.id ? { ...x, text: e.target.value } : x
                    )
                  )
                }
              />
            </div>
          ))}
          {duplicate !== null && (
            <p role='alert' className='text-xs text-destructive'>
              {t('editor.duplicatePath', { path: duplicate })}
            </p>
          )}
          <div>
            <Button
              type='button'
              size='sm'
              variant='outline'
              onClick={() => {
                setFiles((xs) => [
                  ...xs,
                  {
                    id: nextId,
                    path: `reference/note-${nextId + 1}.md`,
                    text: '',
                  },
                ])
                setNextId((n) => n + 1)
              }}
            >
              <Plus />
              {t('editor.addFile')}
            </Button>
          </div>
        </section>

        {saveProblems.length > 0 && (
          <ul
            role='alert'
            className='grid list-disc gap-1 rounded-lg border border-destructive/30 bg-destructive/5 py-2 ps-8 pe-3 text-sm text-destructive'
          >
            {saveProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}

        <div className='flex flex-wrap gap-2'>
          <Button
            type='submit'
            disabled={
              save.isPending || !slug.trim() || blocked || duplicate !== null
            }
          >
            {save.isPending
              ? t('editor.saving')
              : existing
                ? t('editor.saveVersion')
                : t('editor.save')}
          </Button>
          {onCancel && (
            <Button type='button' variant='ghost' onClick={onCancel}>
              {t('editor.cancel')}
            </Button>
          )}
        </div>
      </div>

      <aside className='grid gap-5 lg:sticky lg:top-20'>
        <CheckPanel
          filled={filled}
          pending={check.isFetching || debounced !== draft}
          error={check.isError}
          data={check.data}
        />
        {check.data?.agent_skill_md && (
          <section className='grid gap-2' aria-labelledby={`${ids}-preview`}>
            <h3 id={`${ids}-preview`} className='text-sm font-medium'>
              {t('editor.preview.title')}
            </h3>
            <Tabs defaultValue='rendered'>
              <TabsList>
                <TabsTrigger value='rendered'>
                  {t('editor.preview.rendered')}
                </TabsTrigger>
                <TabsTrigger value='source'>
                  {t('editor.preview.source')}
                </TabsTrigger>
              </TabsList>
              <TabsContent
                value='rendered'
                className='max-h-[32rem] overflow-auto rounded-lg border bg-card p-4'
              >
                <Markdown source={check.data.agent_skill_md} />
              </TabsContent>
              <TabsContent value='source'>
                <pre className='max-h-[32rem] overflow-auto rounded-lg border bg-muted/40 px-3 py-2 font-mono text-xs whitespace-pre-wrap'>
                  {check.data.agent_skill_md}
                </pre>
              </TabsContent>
            </Tabs>
          </section>
        )}
      </aside>
    </form>
  )
}

function CheckPanel({
  filled,
  pending,
  error,
  data,
}: {
  filled: boolean
  pending: boolean
  error: boolean
  data: ReturnType<typeof useCheckDraft>['data']
}) {
  const { t } = useTranslation('skills')
  let status: React.ReactNode
  if (!filled) status = <span>{t('editor.check.empty')}</span>
  else if (error)
    status = <span className='text-destructive'>{t('editor.check.error')}</span>
  else if (pending || !data)
    status = (
      <span className='inline-flex items-center gap-1.5'>
        <LoaderCircle className='size-4 animate-spin' aria-hidden />
        {t('editor.check.checking')}
      </span>
    )
  else if (data.ok)
    status = (
      <span className='inline-flex items-center gap-1.5 text-foreground'>
        <CircleCheck className='size-4 text-success' aria-hidden />
        {t('editor.check.ok')}
        <span className='text-muted-foreground'>
          · {t('editor.check.size', { size: formatBytes(data.size) })}
        </span>
      </span>
    )
  else
    status = (
      <span className='inline-flex items-center gap-1.5 text-destructive'>
        <TriangleAlert className='size-4' aria-hidden />
        {t('editor.check.problems', { count: data.problems.length })}
      </span>
    )

  return (
    <section className='grid gap-3 rounded-lg border bg-card p-4'>
      <div className='flex items-center justify-between gap-3'>
        <h3 className='text-sm font-medium'>{t('editor.check.title')}</h3>
        <p
          role='status'
          aria-live='polite'
          className='text-xs text-muted-foreground'
        >
          {status}
        </p>
      </div>
      {filled && data && !data.ok && (
        <ul className='grid list-disc gap-1 ps-5 text-sm text-destructive'>
          {data.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {filled && data && data.warnings.length > 0 && (
        <ul className='grid list-disc gap-1 ps-5 text-sm text-muted-foreground'>
          {data.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {filled && data && data.findings.length > 0 && (
        <FindingList findings={data.findings} />
      )}
    </section>
  )
}

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

/** Loads a local skill's current version, then opens the editor on it. */
export function VersionEditor({
  slug,
  onSaved,
  onCancel,
}: {
  slug: string
  onSaved: (slug: string) => void
  onCancel: () => void
}) {
  const { t } = useTranslation('skills')
  const detail = useSkillDetail(slug)
  const cur = detail.data?.current
  const textFiles =
    cur?.files.filter((f) => !f.binary && f.path !== 'SKILL.md') ?? []
  const files = useQueries({
    queries: textFiles.map((f) => ({
      queryKey: [
        'kemudi-ai',
        'skill-library',
        slug,
        'file',
        cur!.version,
        f.path,
      ],
      queryFn: async () =>
        (
          await api.get<SkillFile>(
            `/skills/${slug}/versions/${cur!.version}/files/${filePath(f.path)}`,
            base
          )
        ).data,
      staleTime: Infinity,
    })),
  })
  if (detail.isError || files.some((f) => f.isError))
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('detail.loadError')}
      </p>
    )
  if (!detail.data || files.some((f) => !f.data))
    return (
      <div className='grid gap-3' aria-label={t('editor.loading')}>
        <Skeleton className='h-8 w-64' />
        <Skeleton className='h-64 w-full' />
      </div>
    )
  const texts = Object.fromEntries(
    files.map((f) => [f.data!.path, f.data!.text ?? ''])
  )
  return (
    <SkillEditor
      key={`${slug}-${cur?.version}`}
      initial={initialFrom(detail.data, texts)}
      existing={detail.data}
      onSaved={onSaved}
      onCancel={onCancel}
    />
  )
}
