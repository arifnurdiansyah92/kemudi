import { Outlet } from '@tanstack/react-router'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

export function Settings() {
  return (
    <>
      <AppHeader crumbs={[{ label: 'Settings' }, { label: 'Appearance' }]} />
      <Main fixed className='max-w-2xl'>
        <Outlet />
      </Main>
    </>
  )
}
