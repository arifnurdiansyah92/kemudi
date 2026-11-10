import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import {
  callbackUrl,
  readToken,
  saveToken,
  SERVICES,
  useImporterAvailable,
  type Service,
} from './services'

type ExternalProject = {
  id: string | number
  name: string
  description?: string
}
type ExternalUser = {
  id: string | number
  full_name: string
  user?: { id: number; full_name_display?: string } | null
  detected_user?: { id: number } | null
}

export function Importer({
  service,
  callback,
}: {
  service: Service
  /** Query parameters the service added when it sent the browser back. */
  callback: Record<string, string | undefined>
}) {
  const label = SERVICES[service].name
  const available = useImporterAvailable(service)
  const [token, setToken] = useState<string | null>(() => readToken(service))
  const [jiraUrl, setJiraUrl] = useState(callback.url ?? '')
  const authorizing = useRef(false)

  const connect = useMutation({
    mutationFn: async () =>
      (
        await api.get<{ url: string }>(`/importers/${service}/auth_url`, {
          params:
            service === 'jira'
              ? { url: jiraUrl }
              : service === 'github'
                ? { uri: callbackUrl(service) }
                : {},
        })
      ).data.url,
    onSuccess: (url) => window.location.assign(url),
    onError: (e) =>
      toast.error(apiErrorMessage(e, `Could not reach ${label}.`)),
  })

  const authorize = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ token: string }>(`/importers/${service}/authorize`, {
          code: callback.code ?? callback.oauth_verifier,
          oauth_verifier: callback.oauth_verifier,
          url: callback.url,
        })
      ).data.token,
    onSuccess: (t) => {
      saveToken(service, t)
      setToken(t)
    },
    onError: (e) =>
      toast.error(
        apiErrorMessage(e, `${label} did not accept the sign-in. Try again.`)
      ),
  })

  const authorizeMutate = authorize.mutate
  // Coming back from the service with a code: trade it for a token once.
  useEffect(() => {
    if (token || authorizing.current || !available.data) return
    if (callback.code || callback.oauth_verifier) {
      authorizing.current = true
      authorizeMutate()
    }
  }, [token, callback, authorizeMutate, available.data])

  return (
    <>
      <AppHeader
        crumbs={[
          { label: 'Projects', to: '/projects' },
          { label: `Import from ${label}` },
        ]}
      />
      <Main className='max-w-2xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          Import from {label}
        </h1>
        {available.isPending ? (
          <Skeleton className='mt-6 h-24 w-full' />
        ) : !available.data ? (
          <p className='mt-4 text-sm text-muted-foreground'>
            The {label} importer is not set up on this server. An administrator
            enables it by setting{' '}
            <code className='rounded bg-muted px-1'>
              {SERVICES[service].env}=True
            </code>{' '}
            with {label} API credentials in the kemudi-back environment.
          </p>
        ) : authorize.isPending ? (
          <p className='mt-6 flex items-center gap-2 text-sm text-muted-foreground'>
            <Loader2 className='size-4 animate-spin' /> Connecting to {label}…
          </p>
        ) : !token ? (
          <div className='mt-6 grid max-w-md gap-4'>
            <p className='text-sm text-muted-foreground'>
              Sign in to {label} and allow Kemudi to read your projects. You
              come back here to choose what to import.
            </p>
            {service === 'jira' && (
              <div className='grid gap-1.5'>
                <Label htmlFor='jira-url'>Jira address</Label>
                <Input
                  id='jira-url'
                  placeholder='https://your-team.atlassian.net'
                  value={jiraUrl}
                  onChange={(e) => setJiraUrl(e.target.value)}
                />
              </div>
            )}
            <div>
              <Button
                onClick={() => connect.mutate()}
                disabled={
                  connect.isPending ||
                  (service === 'jira' && !/^https?:\/\//.test(jiraUrl))
                }
              >
                {connect.isPending && <Loader2 className='animate-spin' />}
                Connect to {label}
              </Button>
            </div>
          </div>
        ) : (
          <Wizard
            service={service}
            token={token}
            onSignOut={() => {
              saveToken(service, null)
              setToken(null)
            }}
          />
        )}
      </Main>
    </>
  )
}

function Wizard({
  service,
  token,
  onSignOut,
}: {
  service: Service
  token: string
  onSignOut: () => void
}) {
  const navigate = useNavigate()
  const label = SERVICES[service].name
  const base = `/importers/${service}`
  const [picked, setPicked] = useState<ExternalProject | null>(null)
  const [bindings, setBindings] = useState<Record<string, string>>({})
  const [form, setForm] = useState({
    name: '',
    description: '',
    template: 'scrum',
    is_private: true,
    keep_external_reference: true,
  })

  const projects = useQuery({
    queryKey: ['import-projects', service, token],
    queryFn: async () =>
      (
        await api.post<ExternalProject[]>(
          `/importers/${service}/list_projects`,
          { token }
        )
      ).data,
  })
  const users = useQuery({
    queryKey: ['import-users', service, token, picked?.id],
    enabled: !!picked,
    queryFn: async () =>
      (
        await api.post<ExternalUser[]>(`/importers/${service}/list_users`, {
          token,
          project: picked!.id,
        })
      ).data,
  })
  const run = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ slug?: string; task_id?: string }>(
          `${base}/import_project`,
          {
            token,
            project: picked!.id,
            name: form.name || picked!.name,
            description:
              form.description || picked!.description || picked!.name,
            template: form.template,
            project_type: form.template,
            is_private: form.is_private,
            keep_external_reference: form.keep_external_reference,
            users_bindings: Object.fromEntries(
              Object.entries(bindings).filter(([, v]) => v)
            ),
          }
        )
      ).data,
    onSuccess: (data) => {
      if (data.slug) navigate({ to: '/p/$slug', params: { slug: data.slug } })
      else {
        toast.success(
          `Import from ${label} started. You get an email when it is done.`
        )
        navigate({ to: '/projects' })
      }
    },
    onError: (e) =>
      toast.error(apiErrorMessage(e, 'The import could not start.')),
  })

  if (projects.isError)
    return (
      <Alert variant='destructive' className='mt-6'>
        <AlertDescription>
          {apiErrorMessage(
            projects.error,
            `Could not list your ${label} projects.`
          )}{' '}
          <button className='underline' onClick={onSignOut}>
            Connect again
          </button>
        </AlertDescription>
      </Alert>
    )

  return (
    <div className='mt-6 grid gap-6'>
      <section>
        <h2 className='mb-2 font-semibold'>1. Choose a {label} project</h2>
        {projects.isPending ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <ul className='max-h-72 divide-y overflow-y-auto rounded-lg border bg-card'>
            {(projects.data ?? []).map((p) => (
              <li key={p.id}>
                <label className='flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/50'>
                  <input
                    type='radio'
                    name='ext-project'
                    checked={picked?.id === p.id}
                    onChange={() => {
                      setPicked(p)
                      setBindings({})
                      setForm((f) => ({
                        ...f,
                        name: p.name,
                        description: p.description ?? '',
                      }))
                    }}
                  />
                  <span className='font-medium'>{p.name}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </section>

      {picked && (
        <section>
          <h2 className='mb-2 font-semibold'>2. Match people</h2>
          <p className='mb-3 text-sm text-muted-foreground'>
            Enter the Kemudi email of each {label} user to keep their work
            attributed to them. Leave blank to import it without an owner.
          </p>
          {users.isPending ? (
            <Skeleton className='h-16 w-full' />
          ) : (
            <ul className='grid gap-2'>
              {(users.data ?? []).map((u) => (
                <li
                  key={u.id}
                  className='grid items-center gap-2 sm:grid-cols-[14rem_1fr]'
                >
                  <span className='truncate text-sm'>{u.full_name}</span>
                  {u.user || u.detected_user ? (
                    <span className='text-sm text-muted-foreground'>
                      Matched to {u.user?.full_name_display ?? 'a Kemudi user'}
                    </span>
                  ) : (
                    <Input
                      type='email'
                      aria-label={`Kemudi email for ${u.full_name}`}
                      placeholder='name@example.com'
                      value={bindings[String(u.id)] ?? ''}
                      onChange={(e) =>
                        setBindings({
                          ...bindings,
                          [String(u.id)]: e.target.value,
                        })
                      }
                      className='h-8'
                    />
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {picked && (
        <section className='grid gap-3'>
          <h2 className='font-semibold'>3. The new project</h2>
          <div className='grid gap-1.5'>
            <Label htmlFor='imp-name'>Name</Label>
            <Input
              id='imp-name'
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='imp-desc'>Description</Label>
            <Textarea
              id='imp-desc'
              rows={2}
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </div>
          <div className='flex flex-wrap gap-4 text-sm'>
            {(['scrum', 'kanban'] as const).map((t) => (
              <label key={t} className='flex items-center gap-2'>
                <input
                  type='radio'
                  name='imp-template'
                  checked={form.template === t}
                  onChange={() => setForm({ ...form, template: t })}
                />
                {t === 'scrum'
                  ? 'Scrum (backlog and sprints)'
                  : 'Kanban (board)'}
              </label>
            ))}
          </div>
          <label className='flex items-center gap-2 text-sm'>
            <Checkbox
              checked={form.is_private}
              onCheckedChange={(v) =>
                setForm({ ...form, is_private: v === true })
              }
            />
            Private project
          </label>
          <label className='flex items-center gap-2 text-sm'>
            <Checkbox
              checked={form.keep_external_reference}
              onCheckedChange={(v) =>
                setForm({ ...form, keep_external_reference: v === true })
              }
            />
            Keep a link to each original {label} item
          </label>
          <div className='flex gap-2'>
            <Button
              onClick={() => run.mutate()}
              disabled={run.isPending || !form.name.trim()}
            >
              {run.isPending && <Loader2 className='animate-spin' />}
              Import project
            </Button>
            <Button variant='ghost' onClick={onSignOut}>
              Use another {label} account
            </Button>
          </div>
        </section>
      )}
    </div>
  )
}

/** Shown on the new project page: one entry per importer. */
export function ImporterLinks() {
  return (
    <section className='mt-12 border-t pt-8'>
      <h2 className='font-semibold'>Bring a project from another tool</h2>
      <p className='mt-1 text-sm text-muted-foreground'>
        Copies its items, people and history into a new Kemudi project.
      </p>
      <ul className='mt-4 flex flex-wrap gap-2'>
        {(Object.keys(SERVICES) as Service[]).map((s) => (
          <li key={s}>
            <Button variant='outline' size='sm' asChild>
              <Link to='/projects/import/$service' params={{ service: s }}>
                {SERVICES[s].name}
              </Link>
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
