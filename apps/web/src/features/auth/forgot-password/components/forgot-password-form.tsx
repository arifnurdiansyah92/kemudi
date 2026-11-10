import { useMemo, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { apiErrorMessage, requestPasswordReset } from '@/lib/taiga/client'
import { cn } from '@/lib/utils'
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
import { Input } from '@/components/ui/input'

const makeSchema = (t: TFunction<'auth'>) =>
  z.object({
    username: z.string().trim().min(1, t('validation.usernameRequired')),
  })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

export function ForgotPasswordForm({
  className,
  ...props
}: React.HTMLAttributes<HTMLFormElement>) {
  const { t } = useTranslation('auth')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const formSchema = useMemo(() => makeSchema(t), [t])

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { username: '' },
  })

  async function onSubmit({ username }: FormValues) {
    setError(null)
    try {
      await requestPasswordReset(username)
      setSentTo(username)
    } catch (err) {
      setError(apiErrorMessage(err, t('forgotPassword.failed')))
    }
  }

  if (sentTo)
    return (
      <Alert>
        <AlertDescription>
          <Trans
            t={t}
            i18nKey='forgotPassword.sent'
            values={{ username: sentTo }}
            components={{ strong: <strong /> }}
          />
        </AlertDescription>
      </Alert>
    )

  const submitting = form.formState.isSubmitting

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className={cn('grid gap-4', className)}
        {...props}
      >
        {error && (
          <Alert variant='destructive'>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <FormField
          control={form.control}
          name='username'
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t('fields.usernameOrEmail')}</FormLabel>
              <FormControl>
                <Input autoComplete='username' autoFocus {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button className='mt-2' disabled={submitting}>
          {submitting && <Loader2 className='animate-spin' />}
          {t('forgotPassword.submit')}
        </Button>
      </form>
    </Form>
  )
}
