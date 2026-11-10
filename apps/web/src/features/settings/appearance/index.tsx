import { ContentSection } from '../components/content-section'
import { AppearanceForm } from './appearance-form'

export function SettingsAppearance() {
  return (
    <ContentSection
      title='Appearance'
      desc='Choose the font and theme Kemudi uses on this device.'
    >
      <AppearanceForm />
    </ContentSection>
  )
}
