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
      url: '/media/design.png',
      thumbnail_card_url: '/media/design.png.96x96_q85_crop.png',
    })
    mocks.files = [image]

    const screen = await renderAttachments()

    expect(
      document.querySelectorAll('a[href="/media/design.png"]')
    ).toHaveLength(0)

    await userEvent.click(
      screen.getByRole('button', { name: 'View design.png' })
    )

    const dialog = screen.getByRole('dialog', { name: 'design.png' })
    await expect.element(dialog).toBeInTheDocument()
    await expect
      .element(dialog.getByRole('img', { name: 'design.png' }))
      .toHaveAttribute('src', '/media/design.png')
  })

  it('closes the modal again', async () => {
    mocks.files = [attachment({ name: 'photo.jpg', url: '/media/photo.jpg' })]

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
