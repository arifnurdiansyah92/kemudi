import { useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Loader2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { api, apiErrorMessage } from '@/lib/taiga/client'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'

/** Restores a project from a Taiga or Kemudi export file (.json or .json.gz). */
export function ImportDump() {
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
      else
        toast.success(
          'Import started. You get an email when the project is ready.'
        )
    },
    onError: (e) =>
      toast.error(apiErrorMessage(e, 'That file could not be imported.')),
  })

  return (
    <section className='mt-12 border-t pt-8'>
      <h2 className='font-semibold'>Import a project</h2>
      <p className='mt-1 text-sm text-muted-foreground'>
        Restore a project from an export file made by Kemudi or Taiga (Settings,
        Import and export).
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
        Choose export file
      </Button>
    </section>
  )
}
