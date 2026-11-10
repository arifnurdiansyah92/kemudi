import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, type RenderResult } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { SearchProvider } from '@/context/search-provider'

const COMMAND_MENU_PLACEHOLDER = 'Jump to a view, project or story'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  setTheme: vi.fn(),
}))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    useParams: () => ({}),
  }
})

// No project is open; the user belongs to one project.
vi.mock('@/lib/taiga/queries', async (orig) => ({
  ...(await orig<typeof import('@/lib/taiga/queries')>()),
  useProjects: () => ({
    data: [{ id: 2, name: 'Kemudi Demo', slug: 'kemudi-demo' }],
  }),
}))

vi.mock('@/context/theme-provider', () => ({
  useTheme: () => ({ setTheme: mocks.setTheme }),
}))

type ShortcutModifier = 'Control' | 'Meta'

async function renderWithSearchProvider() {
  return await render(
    <QueryClientProvider client={new QueryClient()}>
      <SearchProvider>{null}</SearchProvider>
    </QueryClientProvider>
  )
}

/**
 * Open the palette by shortcut, retrying while the keydown listener may not be mounted yet.
 * Waits between attempts so a successful toggle is not immediately undone by a second chord.
 */
async function openCommandPalette(
  screen: RenderResult,
  modifier: ShortcutModifier = 'Control'
) {
  await vi.waitFor(
    async () => {
      const isCommandPaletteOpen =
        document.querySelector(
          `[placeholder="${COMMAND_MENU_PLACEHOLDER}"]`
        ) !== null

      if (!isCommandPaletteOpen) {
        await userEvent.keyboard(`{${modifier}>}k{/${modifier}}`)
      }

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .toBeInTheDocument()
    },
    { interval: 50, timeout: 5000 }
  )
}

describe('SearchProvider and CommandMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the command palette when the palette is open', async () => {
    const screen = await renderWithSearchProvider()
    const { getByPlaceholder, getByText } = screen

    await openCommandPalette(screen)

    await expect
      .element(getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .toBeInTheDocument()
    await expect.element(getByText('Theme')).toBeInTheDocument()
    await expect.element(getByText('Light')).toBeInTheDocument()
    await expect.element(getByText('Dark')).toBeInTheDocument()
    await expect.element(getByText('Match system')).toBeInTheDocument()
    await expect.element(getByText('Kemudi Demo')).toBeInTheDocument()
  })

  it('does not show the dialog content when search is closed', async () => {
    const { getByPlaceholder } = await renderWithSearchProvider()

    await expect
      .element(getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it.each([
    ['Ctrl', 'Control'],
    ['Cmd', 'Meta'],
  ] as const)(
    'opens the command menu when %s + K is pressed',
    async (_label, modifier) => {
      const screen = await renderWithSearchProvider()

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .not.toBeInTheDocument()

      await openCommandPalette(screen, modifier)

      await expect
        .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
        .toBeInTheDocument()
    }
  )

  it('navigates to a view and closes the palette when a nav item is selected', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByRole('option', { name: 'Projects' }))

    expect(mocks.navigate).toHaveBeenCalledWith({ to: '/' })
    await expect
      .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('opens a project from the projects group', async () => {
    const screen = await renderWithSearchProvider()
    const { getByPlaceholder, getByRole } = screen

    await openCommandPalette(screen)

    await userEvent.click(getByRole('option', { name: 'Kemudi Demo' }))

    expect(mocks.navigate).toHaveBeenCalledWith({
      to: '/p/$slug',
      params: { slug: 'kemudi-demo' },
    })
    await expect
      .element(getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('applies theme and closes the palette when a theme command is chosen', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.click(screen.getByText('Dark'))

    expect(mocks.setTheme).toHaveBeenCalledWith('dark')
    await expect
      .element(screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER))
      .not.toBeInTheDocument()
  })

  it('shows empty state when the filter matches nothing', async () => {
    const screen = await renderWithSearchProvider()

    await openCommandPalette(screen)

    await userEvent.fill(
      screen.getByPlaceholder(COMMAND_MENU_PLACEHOLDER),
      'zzzz-no-match-xxxx'
    )

    await expect
      .element(screen.getByText('Nothing matches.'))
      .toBeInTheDocument()
  })
})
