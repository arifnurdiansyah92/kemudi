import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import {
  Bookmark,
  BookmarkMinus,
  Eye,
  FilePlus,
  Loader2,
  MoreHorizontal,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { Project } from '@/lib/taiga/types'
import {
  pageTitle,
  slugify,
  useDeleteWikiPage,
  useRenderMarkdown,
  useSaveWikiPage,
  useWatchWikiPage,
  useWikiLinkMutations,
  useWikiLinks,
  useWikiPage,
  useWikiPages,
  type WikiPage,
} from '@/lib/taiga/wiki'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { MentionTextarea } from '@/components/mention-textarea'
import { Attachments } from '@/features/item/attachments'
import { can, useProject } from '@/features/project/use-project'
import { WikiHistory } from './history'

export function Wiki({ slug, edit = false }: { slug: string; edit?: boolean }) {
  const { t } = useTranslation(['pages', 'common'])
  const project = useProject()
  const page = useWikiPage(project.id, slug)
  const canAddPage = can(project, 'add_wiki_page')
  const [editing, setEditing] = useState(edit)

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          {
            label: t('common:terms.wiki'),
            to: '/p/$slug/wiki',
            params: { slug: project.slug },
          },
          { label: pageTitle(slug) },
        ]}
      />
      <Main width='list'>
        <div className='grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]'>
          <WikiNav project={project} current={slug} />
          <article className='min-w-0'>
            {page.isPending ? (
              <div className='space-y-3'>
                <Skeleton className='h-8 w-1/3' />
                <Skeleton className='h-40 w-full' />
              </div>
            ) : editing ? (
              <Editor
                project={project}
                slug={slug}
                page={page.data ?? null}
                onDone={() => setEditing(false)}
              />
            ) : page.data ? (
              <PageView
                project={project}
                page={page.data}
                onEdit={() => setEditing(true)}
              />
            ) : (
              <div>
                <h1 className='text-2xl font-semibold tracking-tight'>
                  {pageTitle(slug)}
                </h1>
                <div className='mt-6 rounded-lg border border-dashed p-10 text-center'>
                  <p className='font-medium'>{t('wiki.missing.title')}</p>
                  <p className='mt-1 text-sm text-muted-foreground'>
                    {t('wiki.missing.hint')}
                  </p>
                  {canAddPage && (
                    <Button className='mt-4' onClick={() => setEditing(true)}>
                      {t('wiki.missing.write')}
                    </Button>
                  )}
                </div>
              </div>
            )}
          </article>
        </div>
      </Main>
    </>
  )
}

function PageView({
  project,
  page,
  onEdit,
}: {
  project: Project
  page: WikiPage
  onEdit: () => void
}) {
  const { t } = useTranslation(['pages', 'common'])
  const { timeAgo } = useFormat()
  const navigate = useNavigate()
  const watch = useWatchWikiPage(project)
  const remove = useDeleteWikiPage(project)
  const links = useWikiLinks(project.id)
  const { add, remove: unbookmark } = useWikiLinkMutations(project)
  const [deleting, setDeleting] = useState(false)
  const bookmark = links.data?.find((l) => l.href === page.slug)
  const editor = project.members.find((m) => m.id === page.last_modifier)
  const allowed = {
    edit: can(project, 'modify_wiki_page'),
    bookmark: can(project, 'add_wiki_link'),
    unbookmark: can(project, 'delete_wiki_link'),
    delete: can(project, 'delete_wiki_page'),
  }

  return (
    <>
      <header className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-semibold tracking-tight'>
            {pageTitle(page.slug)}
          </h1>
          <p className='mt-1 text-sm text-muted-foreground'>
            {editor
              ? t('wiki.view.editedBy', {
                  when: timeAgo(page.modified_date),
                  name: editor.full_name_display,
                  count: page.editions,
                })
              : t('wiki.view.edited', {
                  when: timeAgo(page.modified_date),
                  count: page.editions,
                })}
          </p>
        </div>
        <div className='flex items-center gap-1'>
          <Button
            variant='ghost'
            size='sm'
            aria-pressed={page.is_watcher}
            onClick={() => watch.mutate(page)}
          >
            <Eye className={cn(page.is_watcher && 'text-brass')} />
            {page.is_watcher ? t('wiki.view.watching') : t('wiki.view.watch')}
          </Button>
          {allowed.edit && (
            <Button size='sm' variant='outline' onClick={onEdit}>
              {t('wiki.view.editPage')}
            </Button>
          )}
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button
                variant='ghost'
                size='icon'
                className='size-8'
                aria-label={t('wiki.view.moreActions')}
              >
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align='end'>
              {allowed.bookmark && !bookmark && (
                <DropdownMenuItem
                  onSelect={() =>
                    add.mutate({ title: pageTitle(page.slug), href: page.slug })
                  }
                >
                  <Bookmark />
                  {t('wiki.view.bookmark')}
                </DropdownMenuItem>
              )}
              {allowed.unbookmark && bookmark && (
                <DropdownMenuItem onSelect={() => unbookmark.mutate(bookmark)}>
                  <BookmarkMinus />
                  {t('wiki.view.removeBookmark')}
                </DropdownMenuItem>
              )}
              {allowed.delete && (
                <DropdownMenuItem
                  variant='destructive'
                  onSelect={() => setDeleting(true)}
                >
                  {t('wiki.view.deletePage')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {page.content ? (
        <div
          className='rich-text mt-6 max-w-[72ch]'
          dangerouslySetInnerHTML={{ __html: page.html }}
        />
      ) : (
        <p className='mt-6 text-sm text-muted-foreground'>
          {t('wiki.view.empty')}
        </p>
      )}

      <section className='mt-10 border-t pt-6'>
        <h2 className='mb-3 text-sm font-semibold'>
          {t('common:terms.attachments')}
        </h2>
        <Attachments project={project} kind='wiki' item={page} />
      </section>
      <WikiHistory key={page.version} pageId={page.id} />

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t('wiki.deleteDialog.title', { title: pageTitle(page.slug) })}
        desc={t('wiki.deleteDialog.desc')}
        confirmText={t('wiki.view.deletePage')}
        destructive
        isLoading={remove.isPending}
        handleConfirm={() =>
          remove.mutate(page, {
            onSuccess: () => {
              setDeleting(false)
              if (bookmark) unbookmark.mutate(bookmark)
              navigate({ to: '/p/$slug/wiki', params: { slug: project.slug } })
            },
          })
        }
      />
    </>
  )
}

function Editor({
  project,
  slug,
  page,
  onDone,
}: {
  project: Project
  slug: string
  page: WikiPage | null
  onDone: () => void
}) {
  const { t } = useTranslation(['pages', 'common'])
  const save = useSaveWikiPage(project, slug)
  const render = useRenderMarkdown(project)
  const [content, setContent] = useState(page?.content ?? '')

  return (
    <form
      className='grid gap-3'
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate({ page, content }, { onSuccess: onDone })
      }}
    >
      <h1 className='text-2xl font-semibold tracking-tight'>
        {page
          ? t('wiki.editor.titleEdit', { title: pageTitle(slug) })
          : t('wiki.editor.titleWrite', { title: pageTitle(slug) })}
      </h1>
      <Tabs
        defaultValue='write'
        onValueChange={(v) => v === 'preview' && render.mutate(content)}
      >
        <TabsList>
          <TabsTrigger value='write'>{t('wiki.editor.write')}</TabsTrigger>
          <TabsTrigger value='preview'>{t('wiki.editor.preview')}</TabsTrigger>
        </TabsList>
        <TabsContent value='write' className='mt-3'>
          <MentionTextarea
            project={project}
            value={content}
            onChange={setContent}
            rows={20}
            autoFocus
            aria-label={t('wiki.editor.contentLabel')}
            className='font-mono text-sm'
            placeholder={t('wiki.editor.placeholder')}
          />
          <p className='mt-2 text-xs text-muted-foreground'>
            {t('wiki.editor.help')}
          </p>
        </TabsContent>
        <TabsContent
          value='preview'
          className='mt-3 min-h-40 rounded-md border p-4'
        >
          {render.isPending ? (
            <Skeleton className='h-24 w-full' />
          ) : render.data ? (
            <div
              className='rich-text'
              dangerouslySetInnerHTML={{ __html: render.data }}
            />
          ) : (
            <p className='text-sm text-muted-foreground'>
              {t('wiki.editor.nothingToPreview')}
            </p>
          )}
        </TabsContent>
      </Tabs>
      <div className='flex gap-2'>
        <Button type='submit' disabled={save.isPending}>
          {save.isPending && <Loader2 className='animate-spin' />}
          {t('wiki.editor.save')}
        </Button>
        <Button type='button' variant='ghost' onClick={onDone}>
          {t('common:actions.cancel')}
        </Button>
      </div>
    </form>
  )
}

function WikiNav({ project, current }: { project: Project; current: string }) {
  const { t } = useTranslation(['pages', 'common'])
  const links = useWikiLinks(project.id)
  const pages = useWikiPages(project.id)
  const canAddPage = can(project, 'add_wiki_page')
  const [creating, setCreating] = useState(false)

  const item = (slug: string, label: string) => (
    <li key={slug}>
      <Link
        to='/p/$slug/wiki/$page'
        params={{ slug: project.slug, page: slug }}
        className={cn(
          'block truncate rounded-md px-2 py-1 text-sm hover:bg-accent',
          slug === current && 'bg-accent font-medium'
        )}
      >
        {label}
      </Link>
    </li>
  )

  return (
    <nav
      aria-label={t('common:terms.wiki')}
      className='space-y-6 lg:sticky lg:top-20 lg:self-start'
    >
      <div>
        <h2 className='mb-1.5 px-2 text-xs font-medium text-muted-foreground'>
          {t('wiki.nav.bookmarks')}
        </h2>
        {links.data?.length ? (
          <ul>{links.data.map((l) => item(l.href, l.title))}</ul>
        ) : (
          <p className='px-2 text-sm text-muted-foreground'>
            {t('wiki.nav.bookmarksEmpty')}
          </p>
        )}
      </div>
      <div>
        <h2 className='mb-1.5 px-2 text-xs font-medium text-muted-foreground'>
          {t('wiki.nav.allPages')}
        </h2>
        <ul>
          {(pages.data ?? []).map((p) => item(p.slug, pageTitle(p.slug)))}
        </ul>
        {canAddPage && (
          <Button
            variant='ghost'
            size='sm'
            className='mt-1 w-full justify-start text-muted-foreground'
            onClick={() => setCreating(true)}
          >
            <FilePlus />
            {t('wiki.nav.newPage')}
          </Button>
        )}
      </div>
      <NewPageDialog
        project={project}
        open={creating}
        onOpenChange={setCreating}
      />
    </nav>
  )
}

function NewPageDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation(['pages', 'common'])
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const slug = slugify(name)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            if (!slug) return
            onOpenChange(false)
            setName('')
            navigate({
              to: '/p/$slug/wiki/$page',
              params: { slug: project.slug, page: slug },
              search: { edit: true },
            })
          }}
        >
          <DialogHeader>
            <DialogTitle>{t('wiki.nav.newPage')}</DialogTitle>
            <DialogDescription>
              {t('wiki.newPage.desc', {
                slug: slug || t('wiki.newPage.slugFallback'),
              })}
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-1.5'>
            <Label htmlFor='wiki-name'>{t('wiki.newPage.nameLabel')}</Label>
            <Input
              id='wiki-name'
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('wiki.newPage.namePlaceholder')}
            />
          </div>
          <DialogFooter>
            <Button type='submit' disabled={!slug}>
              {t('wiki.newPage.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
