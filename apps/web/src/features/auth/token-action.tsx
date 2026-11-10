import { useEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { AuthLayout } from './auth-layout'

type Props = {
  title: string
  /** POST target and body for the token in the emailed link. */
  endpoint: string
  body: Record<string, string>
  done: string
  failed: string
  /** Ask before acting (for destructive links); otherwise act on load. */
  confirm?: { label: string; text: string }
}

/** Pages that complete an action from an emailed link. */
export function TokenAction({
  title,
  endpoint,
  body,
  done,
  failed,
  confirm,
}: Props) {
  const { t } = useTranslation('auth')
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'failed'>(
    confirm ? 'idle' : 'working'
  )
  const [error, setError] = useState('')
  const started = useRef(false)

  const run = () => {
    setState('working')
    api
      .post(endpoint, body)
      .then(() => setState('done'))
      .catch((e) => {
        setError(apiErrorMessage(e, failed))
        setState('failed')
      })
  }

  useEffect(() => {
    if (confirm || started.current) return
    started.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per link
  }, [])

  return (
    <AuthLayout title={title}>
      {state === 'idle' && confirm && (
        <div className='grid gap-4'>
          <p className='text-sm text-muted-foreground'>{confirm.text}</p>
          <Button variant='destructive' onClick={run}>
            {confirm.label}
          </Button>
        </div>
      )}
      {state === 'working' && (
        <p className='flex items-center gap-2 text-sm text-muted-foreground'>
          <Loader2 className='size-4 animate-spin' /> {t('tokenAction.working')}
        </p>
      )}
      {state === 'done' && (
        <Alert>
          <AlertDescription>
            {done}{' '}
            <Link to='/' className='underline underline-offset-4'>
              {t('tokenAction.goHome')}
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {state === 'failed' && (
        <Alert variant='destructive'>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </AuthLayout>
  )
}
