import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from './use-project'

/** Landing page of a "become the owner" email: accept or decline. */
export function TransferOwnership({ token }: { token: string }) {
  const { t } = useTranslation(['shell', 'common'])
  const project = useProject()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [reason, setReason] = useState('')
  const valid = useQuery({
    queryKey: ['transfer', project.id, token],
    retry: false,
    queryFn: () =>
      api.post(`/projects/${project.id}/transfer_validate_token`, { token }),
  })
  const answer = useMutation({
    mutationFn: (accept: boolean) =>
      api.post(
        `/projects/${project.id}/transfer_${accept ? 'accept' : 'reject'}`,
        {
          token,
          reason,
        }
      ),
    onSuccess: (_d, accept) => {
      toast.success(
        accept
          ? t('transfer.accepted', { project: project.name })
          : t('transfer.declined')
      )
      qc.invalidateQueries({ queryKey: ['project'] })
      navigate({ to: '/p/$slug', params: { slug: project.slug } })
    },
    onError: onFail,
  })

  return (
    <>
      <AppHeader
        crumbs={[{ label: project.name }, { label: t('transfer.crumb') }]}
      />
      <Main className='max-w-xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('transfer.title', { project: project.name })}
        </h1>
        {valid.isPending ? (
          <Skeleton className='mt-6 h-32 w-full' />
        ) : valid.isError ? (
          <p className='mt-4 text-sm text-muted-foreground'>
            {t('transfer.invalid', {
              error: apiErrorMessage(valid.error, t('transfer.invalidLink')),
            })}
          </p>
        ) : (
          <div className='mt-6 grid gap-4'>
            <p className='text-sm text-muted-foreground'>
              {t('transfer.explain')}
            </p>
            <div className='grid gap-1.5'>
              <Label htmlFor='tr-reason'>{t('transfer.message')}</Label>
              <Textarea
                id='tr-reason'
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
            <div className='flex gap-2'>
              <Button
                onClick={() => answer.mutate(true)}
                disabled={answer.isPending}
              >
                {answer.isPending && <Loader2 className='animate-spin' />}
                {t('transfer.accept')}
              </Button>
              <Button
                variant='outline'
                onClick={() => answer.mutate(false)}
                disabled={answer.isPending}
              >
                {t('transfer.decline')}
              </Button>
            </div>
          </div>
        )}
      </Main>
    </>
  )
}
