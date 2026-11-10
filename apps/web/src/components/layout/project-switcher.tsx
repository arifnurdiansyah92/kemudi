import { Link, useParams } from '@tanstack/react-router'
import { Check, ChevronsUpDown } from 'lucide-react'
import { Logo } from '@/assets/logo'
import { useProjects } from '@/lib/taiga/queries'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'

export function ProjectSwitcher() {
  const { isMobile } = useSidebar()
  const { slug } = useParams({ strict: false }) as { slug?: string }
  const { data: projects = [] } = useProjects()
  const current = projects.find((p) => p.slug === slug)

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size='lg'
              className='data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground'
            >
              <div className='flex aspect-square size-8 items-center justify-center rounded-md bg-sidebar-accent text-sidebar-primary'>
                <Logo className='size-5' />
              </div>
              <div className='grid flex-1 text-start leading-tight'>
                <span className='truncate text-sm font-semibold text-sidebar-accent-foreground'>
                  Kemudi
                </span>
                <span className='truncate text-xs'>
                  {current?.name ?? 'Choose a project'}
                </span>
              </div>
              <ChevronsUpDown className='ms-auto' />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className='w-(--radix-dropdown-menu-trigger-width) min-w-60'
            align='start'
            side={isMobile ? 'bottom' : 'right'}
            sideOffset={4}
          >
            <DropdownMenuLabel className='text-xs font-normal text-muted-foreground'>
              Your projects
            </DropdownMenuLabel>
            {projects.map((project) => (
              <DropdownMenuItem key={project.id} asChild>
                <Link to='/p/$slug' params={{ slug: project.slug }}>
                  <span className='truncate'>{project.name}</span>
                  {project.slug === slug && <Check className='ms-auto' />}
                </Link>
              </DropdownMenuItem>
            ))}
            {projects.length === 0 && (
              <p className='px-2 py-1.5 text-sm text-muted-foreground'>
                You are not a member of any project yet.
              </p>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to='/projects'>All projects</Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
