import { languages } from '@/i18n'
import { useLanguage } from '@/i18n/use-language'
import { Languages } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

/**
 * ID / EN toggle. Each option names itself in its own language so someone
 * who can't read the current one still finds theirs.
 */
export function LanguageSwitch({ className }: { className?: string }) {
  const { t } = useTranslation()
  const { language, setLanguage } = useLanguage()
  return (
    <div
      role='radiogroup'
      aria-label={t('language.label')}
      className={cn(
        'inline-flex items-center gap-0.5 rounded-md border p-0.5 text-xs',
        className
      )}
    >
      <Languages aria-hidden className='mx-1 size-3.5 text-muted-foreground' />
      {languages.map((lng) => (
        <button
          key={lng}
          type='button'
          role='radio'
          aria-checked={language === lng}
          lang={lng}
          title={t(`language.${lng}`)}
          onClick={() => setLanguage(lng)}
          className={cn(
            'rounded-sm px-2 py-1 font-medium uppercase transition-colors',
            language === lng
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
          )}
        >
          {lng}
        </button>
      ))}
    </div>
  )
}
