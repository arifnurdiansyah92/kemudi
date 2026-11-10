import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link, useParams } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
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

const formSchema = z
  .object({
    password: z.string().min(6, 'Use at least 6 characters.'),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    path: ['confirm'],
    message: 'The passwords do not match.',
  })

/** Landing page for the reset link taiga-back emails: /change-password/<token>. */
export function ChangePassword() {
  const { token } = useParams({ from: '/(auth)/change-password/$token' })
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: { password: '', confirm: '' },
  })

  async function onSubmit({ password }: z.infer<typeof formSchema>) {
    setError(null)
    try {
      await api.post('/users/change_password_from_recovery', {
        token,
        password,
      })
      setDone(true)
    } catch (err) {
      setError(
        apiErrorMessage(
          err,
          'This reset link is invalid or has expired. Request a new one.'
        )
      )
    }
  }

  return (
    <AuthLayout title='Choose a new password'>
      {done ? (
        <Alert>
          <AlertDescription>
            Your password is changed.{' '}
            <Link to='/sign-in' className='underline underline-offset-4'>
              Sign in
            </Link>{' '}
            with the new one.
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
                  <FormLabel>New password</FormLabel>
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
                  <FormLabel>Repeat it</FormLabel>
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
              Change password
            </Button>
          </form>
        </Form>
      )}
    </AuthLayout>
  )
}
