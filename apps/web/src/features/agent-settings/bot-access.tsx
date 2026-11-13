import { useFormat } from '@/i18n/format'
import { CircleAlert, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useGiveBotAccess, type AgentSettings } from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

/**
 * Awak works in Taiga as one bot user; Taiga hides a project from a user who
 * is not a member, so nothing is picked up. Shown while Awak is on.
 */
export function BotAccessNotice({
  slug,
  settings,
  canEdit,
}: {
  slug: string
  settings: AgentSettings
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const give = useGiveBotAccess(slug)
  const access = settings.bot_access
  if (!settings.enabled || !access || access.ok) return null

  const notMember = access.member === false
  return (
    <Alert variant='destructive'>
      <CircleAlert />
      <AlertTitle>{t('botAccess.title')}</AlertTitle>
      <AlertDescription className='grid gap-3'>
        <p>{notMember ? t('botAccess.notMember') : access.error}</p>
        {notMember &&
          (canEdit ? (
            <div>
              <Button
                size='sm'
                disabled={give.isPending}
                onClick={() =>
                  give.mutate(undefined, {
                    onSuccess: (res) =>
                      toast.success(
                        res.bot_access.ok
                          ? t('botAccess.given')
                          : (res.bot_access.error ?? t('botAccess.notMember'))
                      ),
                  })
                }
              >
                {give.isPending && <Loader2 className='animate-spin' />}
                {t('botAccess.give')}
              </Button>
            </div>
          ) : (
            <p>{t('botAccess.askAdmin')}</p>
          ))}
      </AlertDescription>
    </Alert>
  )
}

/** The worker's last failure for this project, kept quiet: it clears itself
 * on the next good pass. */
export function LastError({ settings }: { settings: AgentSettings }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  if (!settings.last_error) return null
  return (
    <p className='text-xs text-muted-foreground'>
      <span className='font-medium text-foreground'>
        {settings.last_error_at
          ? t('lastError.at', {
              when: f.date(settings.last_error_at, 'dateTime'),
            })
          : t('lastError.label')}
      </span>{' '}
      <span className='break-words'>{settings.last_error}</span>
    </p>
  )
}
