import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage, type NewAccount } from '@/lib/taiga/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/password-input'

const MIN_PASSWORD = 6

/** Fields for a new account; `onSubmit` registers and signs in. */
export function AccountForm({
  email: initialEmail = '',
  submitLabel,
  onSubmit,
}: {
  email?: string
  submitLabel: string
  onSubmit: (account: NewAccount) => Promise<unknown>
}) {
  const { t } = useTranslation('auth')
  const [form, setForm] = useState<NewAccount>({
    username: '',
    full_name: '',
    email: initialEmail,
    password: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (p: Partial<NewAccount>) => setForm({ ...form, ...p })
  const valid =
    form.username.trim() &&
    form.full_name.trim() &&
    /\S+@\S+/.test(form.email) &&
    form.password.length >= MIN_PASSWORD

  return (
    <form
      className='grid gap-4'
      onSubmit={async (e) => {
        e.preventDefault()
        if (!valid) return
        setBusy(true)
        setError(null)
        try {
          await onSubmit({
            ...form,
            username: form.username.trim(),
            full_name: form.full_name.trim(),
            email: form.email.trim(),
          })
        } catch (err) {
          setError(apiErrorMessage(err, t('accountForm.failed')))
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
      <div className='grid gap-1.5'>
        <Label htmlFor='su-name'>{t('fields.fullName')}</Label>
        <Input
          id='su-name'
          autoComplete='name'
          value={form.full_name}
          onChange={(e) => set({ full_name: e.target.value })}
        />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor='su-username'>{t('fields.username')}</Label>
        <Input
          id='su-username'
          autoComplete='username'
          value={form.username}
          onChange={(e) => set({ username: e.target.value })}
        />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor='su-email'>{t('fields.email')}</Label>
        <Input
          id='su-email'
          type='email'
          autoComplete='email'
          value={form.email}
          onChange={(e) => set({ email: e.target.value })}
        />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor='su-password'>{t('fields.password')}</Label>
        <PasswordInput
          id='su-password'
          autoComplete='new-password'
          value={form.password}
          onChange={(e) => set({ password: e.target.value })}
        />
        <p className='text-xs text-muted-foreground'>
          {t('accountForm.passwordHint', { min: MIN_PASSWORD })}
        </p>
      </div>
      <p className='text-xs text-muted-foreground'>{t('accountForm.terms')}</p>
      <Button type='submit' disabled={!valid || busy}>
        {busy && <Loader2 className='animate-spin' />}
        {submitLabel}
      </Button>
    </form>
  )
}
