import {
  Binoculars,
  ChartColumn,
  Lightbulb,
  PenLine,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ProductKind, ProductRunSummary } from '@/lib/kemudi-ai/product'

export const kindIcons: Record<ProductKind, LucideIcon> = {
  competitor: Binoculars,
  features: Lightbulb,
  report: ChartColumn,
  custom: PenLine,
}

const stages = ['context', 'research', 'data', 'writing'] as const

/** What a queued or running run is doing right now, in words. */
export function useStageText() {
  const { t } = useTranslation('agent')
  return (run: Pick<ProductRunSummary, 'status' | 'stage'>) => {
    if (run.status === 'queued') return t('research.stage.queued')
    const stage = stages.find((s) => s === run.stage)
    return stage ? t(`research.stage.${stage}`) : t('research.stage.working')
  }
}
