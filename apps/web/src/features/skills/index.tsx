import { useState } from 'react'
import { Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useKemudiMe } from '@/lib/kemudi-ai/skills'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { MarketplaceTab } from './marketplace'
import { SkillDetailSheet } from './skill-detail'
import { SkillEditor, VersionEditor } from './skill-editor'
import { SkillList } from './skill-list'
import { UploadDialog } from './upload-dialog'

type SkillsTab = 'installed' | 'marketplace' | 'create'

type SkillsSearch = {
  tab?: SkillsTab
  /** The skill open in the detail sheet. */
  skill?: string
  /** On the Create tab: a new version of this local skill. */
  edit?: string
  /** On the Marketplace tab: the marketplace shown. */
  market?: number
}

/** The skill library (/skills): Kemudi admins only. */
export function SkillsPage({
  search,
  navigate,
}: {
  search: SkillsSearch
  navigate: (next: SkillsSearch) => void
}) {
  const { t } = useTranslation('skills')
  const me = useKemudiMe()
  const [uploading, setUploading] = useState(false)
  const tab = search.tab ?? 'installed'
  const openSkill = (slug: string) =>
    navigate({ tab: 'installed', skill: slug })

  let content: React.ReactNode
  if (me.isPending) content = <Skeleton className='mt-8 h-64 w-full' />
  else if (me.isError || !me.data.kemudi_admin)
    content = (
      <div className='mt-8 rounded-lg border border-dashed p-10 text-center'>
        <p className='font-medium'>{t('adminOnly.title')}</p>
        <p className='mx-auto mt-1 max-w-prose text-sm text-muted-foreground'>
          {me.isError ? t('adminOnly.loadError') : t('adminOnly.body')}
        </p>
      </div>
    )
  else
    content = (
      <>
        <Tabs
          value={tab}
          onValueChange={(v) => navigate({ tab: v as SkillsTab })}
          className='mt-6 gap-4'
        >
          <TabsList>
            <TabsTrigger value='installed'>{t('tabs.installed')}</TabsTrigger>
            <TabsTrigger value='marketplace'>
              {t('tabs.marketplace')}
            </TabsTrigger>
            <TabsTrigger value='create'>{t('tabs.create')}</TabsTrigger>
          </TabsList>
          <TabsContent value='installed'>
            <SkillList onOpen={openSkill} />
          </TabsContent>
          <TabsContent value='marketplace'>
            <MarketplaceTab
              selected={search.market ?? null}
              onSelect={(id) => navigate({ tab: 'marketplace', market: id })}
              onOpenSkill={openSkill}
            />
          </TabsContent>
          <TabsContent value='create'>
            {search.edit ? (
              <VersionEditor
                slug={search.edit}
                onSaved={openSkill}
                onCancel={() => openSkill(search.edit!)}
              />
            ) : (
              <SkillEditor onSaved={openSkill} />
            )}
          </TabsContent>
        </Tabs>
        <SkillDetailSheet
          slug={tab === 'installed' ? (search.skill ?? null) : null}
          onClose={() => navigate({ tab: 'installed' })}
          onNewVersion={(slug) => navigate({ tab: 'create', edit: slug })}
        />
        <UploadDialog
          open={uploading}
          onOpenChange={setUploading}
          onOpenSkill={openSkill}
        />
      </>
    )

  return (
    <>
      <AppHeader crumbs={[{ label: t('title') }]} />
      <Main width='list'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>
              {t('title')}
            </h1>
            <p className='mt-1 max-w-prose text-sm text-muted-foreground'>
              {t('intro')}
            </p>
          </div>
          {me.data?.kemudi_admin && (
            <Button size='sm' onClick={() => setUploading(true)}>
              <Upload />
              {t('upload.button')}
            </Button>
          )}
        </div>
        {content}
      </Main>
    </>
  )
}
