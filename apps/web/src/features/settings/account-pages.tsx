import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'
import {
  useApplicationTokens,
  useAvatar,
  useChangePassword,
  useDeleteAccount,
  useLocales,
  useMe,
  useNotifyPolicies,
  useUpdateMe,
  useUpdateNotifyPolicy,
  type Me,
  type NotifyPolicy,
} from '@/lib/taiga/account'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { PasswordInput } from '@/components/password-input'
import { UserAvatar } from '@/components/user-avatar'
import { SettingsSection } from '@/features/project-settings/layout'

/* ---------- profile ---------- */

export function ProfileSettings() {
  const me = useMe()
  if (!me.data) return <Skeleton className='h-64 w-full' />
  return (
    <div className='grid gap-6'>
      <Photo me={me.data} />
      <ProfileForm key={me.data.username + me.data.full_name} me={me.data} />
    </div>
  )
}

function Photo({ me }: { me: Me }) {
  const { change, remove } = useAvatar()
  const input = useRef<HTMLInputElement>(null)
  return (
    <SettingsSection
      title='Photo'
      description='Shown next to your name everywhere in Kemudi.'
    >
      <div className='flex items-center gap-4'>
        <UserAvatar
          user={{ ...me, photo: me.big_photo ?? me.photo }}
          className='size-16'
        />
        <input
          ref={input}
          type='file'
          accept='image/*'
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) change.mutate(file)
            e.target.value = ''
          }}
        />
        <Button
          variant='outline'
          size='sm'
          onClick={() => input.current?.click()}
          disabled={change.isPending}
        >
          {change.isPending && <Loader2 className='animate-spin' />}
          Upload photo
        </Button>
        {me.photo && (
          <Button variant='ghost' size='sm' onClick={() => remove.mutate()}>
            Remove
          </Button>
        )}
      </div>
    </SettingsSection>
  )
}

function ProfileForm({ me }: { me: Me }) {
  const update = useUpdateMe()
  const locales = useLocales()
  const [form, setForm] = useState({
    full_name: me.full_name,
    username: me.username,
    bio: me.bio,
    lang: me.lang,
    timezone: me.timezone,
  })
  const set = (p: Partial<typeof form>) => setForm({ ...form, ...p })
  const zones =
    (
      Intl as { supportedValuesOf?: (k: string) => string[] }
    ).supportedValuesOf?.('timeZone') ?? []

  return (
    <SettingsSection title='About you'>
      <form
        className='grid gap-4'
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate({
            ...form,
            full_name: form.full_name.trim(),
            username: form.username.trim(),
          })
        }}
      >
        <div className='grid gap-4 sm:grid-cols-2'>
          <div className='grid gap-1.5'>
            <Label htmlFor='me-name'>Full name</Label>
            <Input
              id='me-name'
              value={form.full_name}
              onChange={(e) => set({ full_name: e.target.value })}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='me-username'>Username</Label>
            <Input
              id='me-username'
              value={form.username}
              onChange={(e) => set({ username: e.target.value })}
            />
          </div>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='me-bio'>Bio</Label>
          <Textarea
            id='me-bio'
            rows={3}
            maxLength={210}
            value={form.bio}
            onChange={(e) => set({ bio: e.target.value })}
            placeholder='What you work on, in a line or two.'
          />
        </div>
        <div className='grid gap-4 sm:grid-cols-2'>
          <div className='grid gap-1.5'>
            <Label htmlFor='me-lang'>Language of emails</Label>
            <select
              id='me-lang'
              value={form.lang}
              onChange={(e) => set({ lang: e.target.value })}
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>Server default</option>
              {(locales.data ?? []).map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='me-tz'>Time zone</Label>
            <select
              id='me-tz'
              value={form.timezone}
              onChange={(e) => set({ timezone: e.target.value })}
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>Server default</option>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <Button
            type='submit'
            disabled={!form.username.trim() || update.isPending}
          >
            {update.isPending && <Loader2 className='animate-spin' />}
            Save profile
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}

/* ---------- password, email, delete ---------- */

export function AccountSettings() {
  const me = useMe()
  return (
    <div className='grid gap-6'>
      <PasswordForm />
      {me.data && <EmailForm key={me.data.email} me={me.data} />}
      <DeleteAccount />
    </div>
  )
}

function PasswordForm() {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = !!again && next !== again
  return (
    <SettingsSection title='Password'>
      <form
        className='grid max-w-sm gap-3'
        onSubmit={(e) => {
          e.preventDefault()
          if (mismatch || next.length < 6) return
          change.mutate(
            { current_password: current, password: next },
            {
              onSuccess: () => {
                setCurrent('')
                setNext('')
                setAgain('')
              },
            }
          )
        }}
      >
        <div className='grid gap-1.5'>
          <Label htmlFor='pw-current'>Current password</Label>
          <PasswordInput
            id='pw-current'
            autoComplete='current-password'
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='pw-new'>New password</Label>
          <PasswordInput
            id='pw-new'
            autoComplete='new-password'
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='pw-again'>Repeat the new password</Label>
          <PasswordInput
            id='pw-again'
            autoComplete='new-password'
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
          {mismatch && (
            <p className='text-sm text-destructive'>
              The passwords do not match.
            </p>
          )}
        </div>
        <div>
          <Button
            type='submit'
            disabled={
              !current || next.length < 6 || mismatch || change.isPending
            }
          >
            {change.isPending && <Loader2 className='animate-spin' />}
            Change password
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}

function EmailForm({ me }: { me: Me }) {
  const update = useUpdateMe()
  const [email, setEmail] = useState(me.email)
  return (
    <SettingsSection
      title='Email'
      description='Kemudi sends a confirmation link to the new address; the change applies once you open it.'
    >
      <form
        className='flex max-w-md flex-wrap gap-2'
        onSubmit={(e) => {
          e.preventDefault()
          if (email.trim() && email !== me.email)
            update.mutate({ email: email.trim() })
        }}
      >
        <Input
          type='email'
          aria-label='Email'
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className='min-w-56 flex-1'
        />
        <Button
          type='submit'
          variant='outline'
          disabled={!email.trim() || email === me.email}
        >
          Change email
        </Button>
      </form>
      {!me.verified_email && (
        <p className='mt-2 text-sm text-muted-foreground'>
          This address is not confirmed yet. Look for the link in your inbox.
        </p>
      )}
    </SettingsSection>
  )
}

function DeleteAccount() {
  const del = useDeleteAccount()
  const reset = useAuthStore((s) => s.reset)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  return (
    <SettingsSection
      danger
      title='Delete your account'
      description='You are removed from every project and can no longer sign in. Stories, comments and other work you did stay, without your name. Projects you own must be transferred or deleted first.'
    >
      <Button variant='destructive' onClick={() => setOpen(true)}>
        Delete my account
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title='Delete your account?'
        desc='This cannot be undone.'
        confirmText='Delete my account'
        destructive
        isLoading={del.isPending}
        handleConfirm={() =>
          del.mutate(undefined, {
            onSuccess: () => {
              reset()
              qc.clear()
              navigate({ to: '/sign-in', replace: true })
            },
          })
        }
      />
    </SettingsSection>
  )
}

/* ---------- notifications ---------- */

const LEVELS: [NotifyPolicy['notify_level'], string][] = [
  [1, 'All activity'],
  [2, 'Only items I am involved in'],
  [3, 'Nothing'],
]

export function NotificationSettings() {
  const policies = useNotifyPolicies()
  const update = useUpdateNotifyPolicy()
  return (
    <SettingsSection
      title='Notifications per project'
      description='Choose what each project emails you about, and whether it shows in the bell. Involved means items you created, are assigned to or watch.'
    >
      {policies.isPending ? (
        <Skeleton className='h-24 w-full' />
      ) : (
        <div className='overflow-x-auto'>
          <table className='w-full text-sm'>
            <thead className='text-xs text-muted-foreground'>
              <tr>
                <th scope='col' className='py-2 text-start font-medium'>
                  Project
                </th>
                <th scope='col' className='py-2 text-start font-medium'>
                  Email
                </th>
                <th scope='col' className='py-2 text-start font-medium'>
                  In the bell
                </th>
              </tr>
            </thead>
            <tbody className='divide-y'>
              {(policies.data ?? []).map((p) => (
                <tr key={p.id}>
                  <th scope='row' className='py-2 pe-4 text-start font-medium'>
                    {p.project_name}
                  </th>
                  <td className='py-2 pe-4'>
                    <select
                      aria-label={`Email from ${p.project_name}`}
                      value={p.notify_level}
                      onChange={(e) =>
                        update.mutate({
                          policy: p,
                          patch: {
                            notify_level: Number(
                              e.target.value
                            ) as NotifyPolicy['notify_level'],
                          },
                        })
                      }
                      className='h-8 rounded-md border bg-transparent px-2'
                    >
                      {LEVELS.map(([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className='py-2'>
                    <Switch
                      aria-label={`Bell notifications from ${p.project_name}`}
                      checked={p.web_notify_level}
                      onCheckedChange={(v) =>
                        update.mutate({
                          policy: p,
                          patch: { web_notify_level: v },
                        })
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SettingsSection>
  )
}

/* ---------- connected apps ---------- */

export function AppsSettings() {
  const { list, revoke } = useApplicationTokens()
  return (
    <SettingsSection
      title='Connected apps'
      description='Applications you allowed to use Kemudi on your behalf. Revoke one to cut off its access.'
    >
      {list.isPending ? (
        <Skeleton className='h-12 w-full' />
      ) : (list.data ?? []).length === 0 ? (
        <p className='text-sm text-muted-foreground'>
          No apps are connected to your account.
        </p>
      ) : (
        <ul className='divide-y'>
          {list.data!.map((t) => (
            <li key={t.id} className='flex items-center gap-3 py-2.5'>
              <div className='min-w-0 flex-1'>
                <p className='text-sm font-medium'>{t.application.name}</p>
                <p className='truncate text-xs text-muted-foreground'>
                  {t.application.description}
                </p>
              </div>
              <Button
                variant='outline'
                size='sm'
                onClick={() => revoke.mutate(t)}
              >
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  )
}
