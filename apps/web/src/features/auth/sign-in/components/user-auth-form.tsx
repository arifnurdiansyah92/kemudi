import { useMemo, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useNavigate } from '@tanstack/react-router'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { apiErrorMessage, signIn } from '@/lib/taiga/client'
import { cn, safeRedirect } from '@/lib/utils'
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
import { PasswordInput } from '@/components/password-input'

const makeSchema = (t: TFunction<'auth'>) =>
  z.object({
    username: z.string().trim().min(1, t('validation.usernameRequired')),
    password: z.string().min(1, t('validation.passwordRequired')),
  })

type FormValues = z.infer<ReturnType<typeof makeSchema>>

interface UserAuthFormProps extends React.HTMLAttributes<HTMLFormElement> {
  redirectTo?: string
}

export function UserAuthForm({
  className,
  redirectTo,
  ...props
}: UserAuthFormProps) {
  const { t } = useTranslation('auth')
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const formSchema = useMemo(() => makeSchema(t), [t])

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { username: '', password: '' },
  })

  async function onSubmit(data: FormValues) {
    setError(null)
    try {
      await signIn(data.username, data.password)
      navigate({ to: safeRedirect(redirectTo), replace: true })
    } catch (err) {
      setError(apiErrorMessage(err, t('signIn.failed')))
    }
  }

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
        <FormField
          control={form.control}
          name='password'
          render={({ field }) => (
            <FormItem>
              <div className='flex items-baseline justify-between'>
                <FormLabel>{t('fields.password')}</FormLabel>
                <Link
                  to='/forgot-password'
                  className='text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline'
                >
                  {t('signIn.forgotPassword')}
                </Link>
              </div>
              <FormControl>
                <PasswordInput autoComplete='current-password' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button className='mt-2' disabled={submitting}>
          {submitting && <Loader2 className='animate-spin' />}
          {t('signIn.submit')}
        </Button>
      </form>
    </Form>
  )
}
