import { AxiosError } from 'axios'
import { Link, type ErrorComponentProps } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'

export function ProjectError({ error, reset }: ErrorComponentProps) {
  const status =
    error instanceof AxiosError ? error.response?.status : undefined
  const missing = status === 404 || status === 403

  return (
    <div className='flex min-h-[60svh] flex-col items-center justify-center gap-2 px-4 text-center'>
      <h1 className='text-xl font-semibold'>
        {missing ? 'Project not found' : 'This project could not be loaded'}
      </h1>
      <p className='max-w-sm text-sm text-muted-foreground'>
        {missing
          ? 'The link may be wrong, or you are not a member of this project.'
          : 'Check that the Kemudi server is running, then try again.'}
      </p>
      <div className='mt-4 flex gap-2'>
        {!missing && <Button onClick={reset}>Try again</Button>}
        <Button variant='outline' asChild>
          <Link to='/'>All projects</Link>
        </Button>
      </div>
    </div>
  )
}
