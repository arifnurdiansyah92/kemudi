import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import {
  api,
  apiErrorMessage,
  registerFromInvitation,
  signIn,
} from '@/lib/taiga/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PasswordInput } from '@/components/password-input'
import { AuthLayout } from '../auth-layout'
import { AccountForm } from '../sign-up/account-form'

interface Invitation {
  project_name: string
  project_slug: string
  role_name: string
  email: string | null
  invited_by: { full_name_display: string } | null
}

/** Landing page of an invitation email: /invitation/<token>. */
export function InvitationPage({ token }: { token: string }) {
  const { t } = useTranslation('auth')
  const navigate = useNavigate()
  const signedInAs = useAuthStore((s) => s.session?.user.username)
  const invitation = useQuery({
    queryKey: ['invitation', token],
    retry: false,
    queryFn: async () =>
      (await api.get<Invitation>(`/invitations/${token}`)).data,
  })
  const goToProject = () =>
    invitation.data &&
    navigate({
      to: '/p/$slug',
      params: { slug: invitation.data.project_slug },
      replace: true,
    })

  if (invitation.isPending)
    return (
      <AuthLayout title={t('invitation.title')}>
        <Skeleton className='h-40 w-full' />
      </AuthLayout>
    )

  if (invitation.isError)
    return (
      <AuthLayout title={t('invitation.notFoundTitle')}>
        <p className='text-sm text-muted-foreground'>
          {t('invitation.notFound')}
        </p>
      </AuthLayout>
    )

  const inv = invitation.data
  return (
    <AuthLayout
      title={t('invitation.join', { project: inv.project_name })}
      description={
        inv.invited_by
          ? t('invitation.invitedBy', {
              name: inv.invited_by.full_name_display,
              role: inv.role_name,
            })
          : t('invitation.invitedByAdmin', { role: inv.role_name })
      }
    >
      <Tabs defaultValue={signedInAs ? 'existing' : 'new'}>
        <TabsList className='w-full'>
          <TabsTrigger value='new' className='flex-1'>
            {t('invitation.newTab')}
          </TabsTrigger>
          <TabsTrigger value='existing' className='flex-1'>
            {t('invitation.existingTab')}
          </TabsTrigger>
        </TabsList>
        <TabsContent value='new' className='mt-5'>
          <AccountForm
            email={inv.email ?? ''}
            submitLabel={t('invitation.createAndJoin')}
            onSubmit={async (account) => {
              await registerFromInvitation(token, account)
              goToProject()
            }}
          />
        </TabsContent>
        <TabsContent value='existing' className='mt-5'>
          <ExistingAccount
            token={token}
            username={signedInAs ?? ''}
            onDone={goToProject}
          />
        </TabsContent>
      </Tabs>
    </AuthLayout>
  )
}

function ExistingAccount({
  token,
  username: initial,
  onDone,
}: {
  token: string
  username: string
  onDone: () => void
}) {
  const { t } = useTranslation('auth')
  const [username, setUsername] = useState(initial)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <form
      className='grid gap-4'
      onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await signIn(username.trim(), password, token)
          onDone()
        } catch (err) {
          setError(apiErrorMessage(err, t('invitation.signInFailed')))
        } finally {
          setBusy(false)
        }
      }}
    >
      {error && (
        <Alert variant='destructive'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <p className='text-sm text-muted-foreground'>
        {t('invitation.existingHint')}
      </p>
      <div className='grid gap-1.5'>
        <Label htmlFor='inv-user'>{t('fields.usernameOrEmail')}</Label>
        <Input
          id='inv-user'
          autoComplete='username'
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor='inv-pass'>{t('fields.password')}</Label>
        <PasswordInput
          id='inv-pass'
          autoComplete='current-password'
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <Button type='submit' disabled={!username.trim() || !password || busy}>
        {busy && <Loader2 className='animate-spin' />}
        {t('invitation.signInAndJoin')}
      </Button>
    </form>
  )
}
