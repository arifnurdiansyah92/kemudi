import { useMemo } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { commandFields, repoRoles, type RepoIn } from '@/lib/kemudi-ai/agent'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'

/** Mirrors infra/runner/runner.py ALLOWED_PROGRAMS (the server checks too). */
const ALLOWED_PROGRAMS = new Set([
  'pnpm',
  'npm',
  'npx',
  'yarn',
  'node',
  'python',
  'uv',
  'pytest',
  'make',
  'go',
  'cargo',
])

function firstBadProgram(text: string): string | null {
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const program = line.split(/\s+/)[0].replace(/^['"]|['"]$/g, '')
    if (!ALLOWED_PROGRAMS.has(program)) return program
  }
  return null
}

const makeSchema = (t: TFunction<'agent'>) => {
  const command = z
    .string()
    .max(2000)
    .superRefine((v, ctx) => {
      const bad = firstBadProgram(v)
      if (bad)
        ctx.addIssue({
          code: 'custom',
          message: t('repos.form.invalid.program', { program: bad }),
        })
    })
  return z.object({
    name: z
      .string()
      .regex(/^[a-z0-9][a-z0-9-]{0,99}$/, t('repos.form.invalid.name')),
    role: z.enum(['web', 'api', 'mobile', 'other']),
    url: z
      .string()
      .trim()
      .min(1, t('repos.form.invalid.url'))
      .max(500)
      .refine(
        // Kemudi's own repo is a local path; the server decides if it's allowed.
        (v) => !/^https?:\/\//i.test(v),
        t('repos.form.invalid.urlHttps')
      ),
    default_branch: z
      .string()
      .regex(/^[A-Za-z0-9._/-]{1,100}$/, t('repos.form.invalid.branch'))
      .refine(
        (v) => !v.startsWith('-') && !v.includes('..'),
        t('repos.form.invalid.branch')
      ),
    subdir: z
      .string()
      .trim()
      .max(200)
      .refine(
        (v) =>
          !v.startsWith('/') &&
          !v.includes(':') &&
          !v.split(/[\\/]/).includes('..'),
        t('repos.form.invalid.subdir')
      ),
    install_cmd: command,
    check_cmd: command,
    build_cmd: command,
    run_cmd: command,
  })
}

const textareaClass =
  'w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive read-only:bg-muted/50'

/** Add or edit a repo. `values` resets the form when the server answers. */
export function RepoForm({
  values,
  isNew,
  canEdit,
  pending,
  onSubmit,
}: {
  values: RepoIn
  isNew: boolean
  canEdit: boolean
  pending: boolean
  onSubmit: (repo: RepoIn) => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const schema = useMemo(() => makeSchema(t as TFunction<'agent'>), [t])
  const form = useForm<RepoIn>({
    resolver: zodResolver(schema),
    values,
  })
  const ro = !canEdit
  // Commands may have been filled by Check access: save what the server has.
  const dirty = form.formState.isDirty

  return (
    <Form {...form}>
      <form
        className='grid gap-4'
        onSubmit={form.handleSubmit((v) => onSubmit(v))}
        noValidate
      >
        <div className='grid items-start gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]'>
          <FormField
            control={form.control}
            name='name'
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('repos.form.name')}</FormLabel>
                <FormControl>
                  <Input {...field} readOnly={ro} spellCheck={false} />
                </FormControl>
                <FormDescription>{t('repos.form.nameHint')}</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='role'
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('repos.form.role')}</FormLabel>
                <FormControl>
                  <select
                    {...field}
                    disabled={ro}
                    className='h-9 rounded-md border border-input bg-background px-2 text-sm shadow-xs'
                  >
                    {repoRoles.map((r) => (
                      <option key={r} value={r}>
                        {t(`repos.roles.${r}`)}
                      </option>
                    ))}
                  </select>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <FormField
          control={form.control}
          name='url'
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t('repos.form.url')}</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  readOnly={ro}
                  spellCheck={false}
                  autoComplete='off'
                  className='font-mono text-xs'
                />
              </FormControl>
              <FormDescription>{t('repos.form.urlHint')}</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='grid items-start gap-4 sm:grid-cols-2'>
          <FormField
            control={form.control}
            name='default_branch'
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('repos.form.branch')}</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    readOnly={ro}
                    spellCheck={false}
                    className='font-mono text-xs'
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name='subdir'
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t('repos.form.subdir')}</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    readOnly={ro}
                    spellCheck={false}
                    className='font-mono text-xs'
                  />
                </FormControl>
                <FormDescription>{t('repos.form.subdirHint')}</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <fieldset className='grid gap-3'>
          <legend className='text-sm font-medium'>
            {t('repos.form.commands')}
          </legend>
          <p className='-mt-1 text-xs text-muted-foreground'>
            {t('repos.form.commandsHint')}
          </p>
          {commandFields.map((name) => (
            <FormField
              key={name}
              control={form.control}
              name={name}
              render={({ field }) => (
                <FormItem>
                  <FormLabel className='font-normal'>
                    {t(`repos.form.${name}`)}
                  </FormLabel>
                  <FormControl>
                    <textarea
                      {...field}
                      readOnly={ro}
                      rows={name === 'check_cmd' ? 3 : 1}
                      spellCheck={false}
                      className={textareaClass}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ))}
        </fieldset>
        {canEdit && (
          <div className='flex gap-2'>
            <Button type='submit' disabled={pending || (!isNew && !dirty)}>
              {pending && <Loader2 className='animate-spin' />}
              {isNew
                ? t('repos.form.submitNew')
                : t('common:actions.saveChanges')}
            </Button>
          </div>
        )}
      </form>
    </Form>
  )
}
