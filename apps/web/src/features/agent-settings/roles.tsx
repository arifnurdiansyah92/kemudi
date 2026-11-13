import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  roleBody,
  useRolePrompt,
  useSaveRole,
  type Repo,
  type Role,
} from '@/lib/kemudi-ai/agent'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { LlmSourceBadge, RoleLlmSection } from './llm-connection'
import { RoleEditor } from './role-editor'

export function Roles({
  slug,
  roles,
  models,
  repos,
  canEdit,
}: {
  slug: string
  roles: Role[]
  models: string[]
  repos: Repo[]
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const save = useSaveRole(slug)
  // null: closed; 0: a new role; otherwise the open role's id.
  const [open, setOpen] = useState<number | null>(null)
  const current = open ? (roles.find((r) => r.id === open) ?? null) : null

  return (
    <div className='grid gap-3'>
      {roles.length === 0 ? (
        <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
          {t('roles.empty')}
        </p>
      ) : (
        <ul className='divide-y rounded-lg border'>
          {roles.map((r) => (
            <li
              key={r.id}
              className='flex items-center gap-3 px-4 py-2 hover:bg-accent/50'
            >
              <Switch
                checked={r.enabled}
                disabled={!canEdit || save.isPending}
                aria-label={t('roles.enabledLabel', { name: r.name })}
                onCheckedChange={(enabled) =>
                  save.mutate(
                    { ...roleBody(r), id: r.id, enabled },
                    {
                      onSuccess: () =>
                        toast.success(
                          enabled ? t('roles.enabled') : t('roles.disabled')
                        ),
                    }
                  )
                }
              />
              <button
                type='button'
                onClick={() => setOpen(r.id)}
                className='grid min-w-0 flex-1 gap-0.5 rounded-sm py-0.5 text-start focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4'
              >
                <span className='truncate text-sm font-medium'>{r.name}</span>
                <span className='flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-muted-foreground'>
                  <span className='font-mono'>{`area:${r.area}`}</span>
                  <span
                    className='flex items-center gap-1.5'
                    title={r.llm_host || undefined}
                  >
                    <LlmSourceBadge source={r.llm_source} />
                    <span className='font-mono'>{r.llm_model}</span>
                  </span>
                  <span>
                    {r.repo_ids.length
                      ? t('roles.repoCount', { count: r.repo_ids.length })
                      : t('roles.editor.reposAll')}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <div>
          <Button size='sm' variant='outline' onClick={() => setOpen(0)}>
            <Plus />
            {t('roles.add')}
          </Button>
        </div>
      )}
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className='w-full gap-0 overflow-y-auto sm:max-w-2xl'>
          {open !== null && (
            <RoleSheetBody
              key={`${open}-${current?.version ?? 0}`}
              slug={slug}
              role={current}
              models={models}
              repos={repos}
              canEdit={canEdit}
              onCreated={setOpen}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function RoleSheetBody({
  slug,
  role,
  models,
  repos,
  canEdit,
  onCreated,
}: {
  slug: string
  role: Role | null
  models: string[]
  repos: Repo[]
  canEdit: boolean
  onCreated: (id: number) => void
}) {
  const { t } = useTranslation('agent')
  const save = useSaveRole(slug)
  const prompt = useRolePrompt(slug, role?.id ?? null)
  return (
    <>
      <SheetHeader className='border-b px-6 py-4'>
        <SheetTitle>
          {role
            ? t('roles.editTitle', { name: role.name })
            : t('roles.newTitle')}
        </SheetTitle>
        <SheetDescription>{t('roles.description')}</SheetDescription>
      </SheetHeader>
      <div className='px-6 py-5'>
        <RoleEditor
          role={role}
          prompt={prompt.data}
          promptPending={prompt.isPending}
          models={models}
          repos={repos}
          canEdit={canEdit}
          pending={save.isPending}
          onSave={(body) =>
            save.mutate(
              { ...body, id: role?.id },
              {
                onSuccess: (saved) => {
                  toast.success(role ? t('roles.saved') : t('roles.created'))
                  if (!role) onCreated(saved.id)
                },
              }
            )
          }
        />
      </div>
      <section className='grid gap-3 border-t px-6 py-5'>
        <div className='grid gap-1'>
          <h3 className='font-semibold'>{t('llm.roleTitle')}</h3>
          <p className='text-sm text-muted-foreground'>
            {t('llm.roleDescription')}
          </p>
        </div>
        {role ? (
          <RoleLlmSection slug={slug} roleId={role.id} canEdit={canEdit} />
        ) : (
          <p className='text-sm text-muted-foreground'>
            {t('llm.roleSaveFirst')}
          </p>
        )}
      </section>
    </>
  )
}
