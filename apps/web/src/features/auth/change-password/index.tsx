import { useMemo, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useParams } from '@tanstack/react-router'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { PasswordInput } from '@/components/password-input'
import { AuthLayout } from '../auth-layout'

const makeSchema = (t: TFunction<'auth'>) =>
  z
    .object({
      password: z.string().min(6, t('validation.passwordMin', { min: 6 })),
      confirm: z.string(),
    })
    .refine((v) => v.password === v.confirm, {
      path: ['confirm'],
      message: t('validation.passwordMismatch'),
    })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

/** Landing page for the reset link taiga-back emails: /change-password/<token>. */
export function ChangePassword() {
  const { t } = useTranslation('auth')
  const { token } = useParams({ from: '/(auth)/change-password/$token' })
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const formSchema = useMemo(() => makeSchema(t), [t])
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { password: '', confirm: '' },
  })

  async function onSubmit({ password }: FormValues) {
    setError(null)
    try {
      await api.post('/users/change_password_from_recovery', {
        token,
        password,
      })
      setDone(true)
    } catch (err) {
      setError(apiErrorMessage(err, t('changePassword.invalidLink')))
    }
  }

  return (
    <AuthLayout title={t('changePassword.title')}>
      {done ? (
        <Alert>
          <AlertDescription>
            <Trans
              t={t}
              i18nKey='changePassword.done'
              components={{
                link: (
                  <Link
                    to='/sign-in'
                    className='underline underline-offset-4'
                  />
                ),
              }}
            />
          </AlertDescription>
        </Alert>
      ) : (
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='grid gap-4'>
            {error && (
              <Alert variant='destructive'>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <FormField
              control={form.control}
              name='password'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('changePassword.newPassword')}</FormLabel>
                  <FormControl>
                    <PasswordInput autoComplete='new-password' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='confirm'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('changePassword.confirm')}</FormLabel>
                  <FormControl>
                    <PasswordInput autoComplete='new-password' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button className='mt-2' disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting && (
                <Loader2 className='animate-spin' />
              )}
              {t('changePassword.submit')}
            </Button>
          </form>
        </Form>
      )}
    </AuthLayout>
  )
}
