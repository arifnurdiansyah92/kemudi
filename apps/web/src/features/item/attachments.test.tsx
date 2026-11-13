import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import type { Attachment, Project } from '@/lib/taiga/types'
import { Attachments } from './attachments'

const mocks = vi.hoisted(() => ({ files: [] as Attachment[] }))

vi.mock('@/lib/taiga/items', () => ({
  KINDS: { userstory: { perm: { modify: 'modify_us' } } },
  useAttachments: () => ({ isPending: false, data: mocks.files }),
  useUploadAttachment: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteAttachment: () => ({ mutate: vi.fn() }),
}))

// The list is read-only here; permissions are exercised elsewhere.
vi.mock('@/features/project/use-project', () => ({ can: () => false }))

const project = { id: 1 } as Project

// Inline payloads: the sandbox has no media server to fetch from, but the
// browser can still decode these, so the test proves the picture renders.
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR42mP4z8AARAwQCgAf7gP9Y167WwAAAABJRU5ErkJggg=='
const THUMB =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='4' height='4'%3E%3Crect width='4' height='4' fill='%23000'/%3E%3C/svg%3E"

function attachment(overrides: Partial<Attachment>): Attachment {
  return {
    id: 1,
    name: 'notes.txt',
    size: 1200,
    url: '/media/notes.txt',
    thumbnail_card_url: null,
    description: '',
    is_deprecated: false,
    created_date: '2026-11-01T10:00:00Z',
    owner: 2,
    ...overrides,
  }
}

async function renderAttachments() {
  return await render(
    <Attachments project={project} kind='userstory' item={{ id: 7 }} />
  )
}

describe('Attachments', () => {
  beforeEach(() => {
    mocks.files = []
  })

  it('shows an image attachment in a modal instead of linking to the file', async () => {
    const image = attachment({
      name: 'design.png',
      url: PNG,
      thumbnail_card_url: THUMB,
    })
    mocks.files = [image]

    const screen = await renderAttachments()

    // Nothing in the row points at the file, so a click cannot start a download.
    expect(document.querySelectorAll('a[href]')).toHaveLength(0)
    expect(document.querySelectorAll('[download]')).toHaveLength(0)

    const trigger = screen.getByRole('button', { name: 'View design.png' })
    expect(trigger.element().closest('a')).toBeNull()
    // Click the thumbnail itself, the way a reader would.
    await userEvent.click(trigger.element().querySelector('img')!)

    const dialog = screen.getByRole('dialog', { name: 'design.png' })
    await expect.element(dialog).toBeInTheDocument()
    const shown = dialog.getByRole('img', { name: 'design.png' })
    await expect.element(shown).toHaveAttribute('src', PNG)
    // The browser decoded the image: the modal shows the picture itself.
    await expect
      .poll(() => (shown.element() as HTMLImageElement).naturalWidth)
      .toBeGreaterThan(0)
  })

  it('closes the modal again', async () => {
    mocks.files = [attachment({ name: 'photo.jpg', url: PNG })]

    const screen = await renderAttachments()
    await userEvent.click(
      screen.getByRole('button', { name: 'View photo.jpg' })
    )
    await expect.element(screen.getByRole('dialog')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await expect.element(screen.getByRole('dialog')).not.toBeInTheDocument()
  })

  it('still links non-image attachments to the file', async () => {
    mocks.files = [
      attachment({ name: 'contract.pdf', url: '/media/contract.pdf' }),
    ]

    const screen = await renderAttachments()

    await expect
      .element(screen.getByRole('link', { name: 'contract.pdf' }))
      .toHaveAttribute('href', '/media/contract.pdf')
    expect(
      screen.getByRole('button', { name: /View contract/ }).length
    ).toBe(0)
  })
})
