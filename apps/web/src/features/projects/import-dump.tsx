import { useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2, Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'

/** Restores a project from a Taiga or Kemudi export file (.json or .json.gz). */
export function ImportDump() {
  const { t } = useTranslation('home')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const load = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('dump', file)
      const res = await api.post<Project | { import_id: string }>(
        '/importer/load_dump',
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      return res.data
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      if ('slug' in data)
        navigate({ to: '/p/$slug', params: { slug: data.slug } })
      else toast.success(t('projects.import.started'))
    },
    onError: (e) =>
      toast.error(apiErrorMessage(e, t('projects.import.failed'))),
  })

  return (
    <section className='mt-12 border-t pt-8'>
      <h2 className='font-semibold'>{t('projects.import.title')}</h2>
      <p className='mt-1 text-sm text-muted-foreground'>
        {t('projects.import.intro')}
      </p>
      <input
        ref={input}
        type='file'
        accept='.json,.gz,application/json,application/gzip'
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) load.mutate(file)
          e.target.value = ''
        }}
      />
      <Button
        variant='outline'
        className='mt-4'
        onClick={() => input.current?.click()}
        disabled={load.isPending}
      >
        {load.isPending ? <Loader2 className='animate-spin' /> : <Upload />}
        {t('projects.import.choose')}
      </Button>
    </section>
  )
}
