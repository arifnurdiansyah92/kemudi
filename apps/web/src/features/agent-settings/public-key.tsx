import { useState } from 'react'
import { Copy, KeyRound, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/confirm-dialog'

/**
 * The public half of a Kemudi-generated SSH key, with copy. It reads only
 * `public_key` and `fingerprint` from what it is given, so whatever else an
 * object carries never reaches the page.
 */
export function PublicKey({
  value,
  id,
}: {
  value: { public_key: string | null; fingerprint: string | null }
  id: string
}) {
  const { t } = useTranslation(['agent', 'common'])
  const publicKey = value.public_key
  if (!publicKey) return null
  return (
    <div className='grid gap-1.5'>
      <div className='flex items-center justify-between gap-2'>
        <label htmlFor={id} className='text-sm font-medium'>
          {t('key.publicKey')}
        </label>
        <Button
          type='button'
          size='sm'
          variant='outline'
          onClick={() =>
            navigator.clipboard
              ?.writeText(publicKey)
              .then(() => toast.success(t('key.copied')))
          }
        >
          <Copy />
          {t('common:actions.copy')}
        </Button>
      </div>
      <textarea
        id={id}
        readOnly
        rows={2}
        value={publicKey}
        onFocus={(e) => e.currentTarget.select()}
        className='w-full resize-none rounded-md border bg-muted/50 px-3 py-2 font-mono text-xs break-all text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'
      />
      {value.fingerprint && (
        <p className='text-xs text-muted-foreground'>
          {t('key.fingerprint')}{' '}
          <span className='font-mono'>{value.fingerprint}</span>
        </p>
      )}
    </div>
  )
}

/** Generate a key, or replace it after a warning that the old one stops working. */
export function KeyButton({
  hasKey,
  pending,
  disabled,
  onGenerate,
}: {
  hasKey: boolean
  pending: boolean
  disabled?: boolean
  onGenerate: () => void
}) {
  const { t } = useTranslation('agent')
  const [confirm, setConfirm] = useState(false)
  return (
    <>
      <Button
        type='button'
        size='sm'
        variant='outline'
        disabled={disabled || pending}
        onClick={() => (hasKey ? setConfirm(true) : onGenerate())}
      >
        {pending ? <Loader2 className='animate-spin' /> : <KeyRound />}
        {hasKey ? t('key.regenerate') : t('key.generate')}
      </Button>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t('key.regenerateTitle')}
        desc={t('key.regenerateBody')}
        confirmText={t('key.regenerate')}
        destructive
        handleConfirm={() => {
          setConfirm(false)
          onGenerate()
        }}
      />
    </>
  )
}
