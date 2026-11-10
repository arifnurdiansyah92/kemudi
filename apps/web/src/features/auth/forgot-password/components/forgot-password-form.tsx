import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2 } from 'lucide-react'
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

const formSchema = z.object({
  username: z.string().trim().min(1, 'Enter your username or email.'),
})

export function ForgotPasswordForm({
  className,
  ...props
}: React.HTMLAttributes<HTMLFormElement>) {
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: { username: '' },
  })

  async function onSubmit({ username }: z.infer<typeof formSchema>) {
    setError(null)
    try {
      await requestPasswordReset(username)
      setSentTo(username)
    } catch (err) {
      setError(apiErrorMessage(err, 'The reset email was not sent. Try again.'))
    }
  }

  if (sentTo)
    return (
      <Alert>
        <AlertDescription>
          If an account matches <strong>{sentTo}</strong>, a reset link is on
          its way to that account's email address.
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
              <FormLabel>Username or email</FormLabel>
              <FormControl>
                <Input autoComplete='username' autoFocus {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button className='mt-2' disabled={submitting}>
          {submitting && <Loader2 className='animate-spin' />}
          Send reset link
        </Button>
      </form>
    </Form>
  )
}
