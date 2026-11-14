import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { DeployCommand, MergePolicy, QaModeControl } from './merge-policy'

describe('MergePolicy', () => {
  it('offers three modes with approve checked and marked default', async () => {
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='browser'
        branch='main'
        canEdit
        onChange={() => {}}
      />
    )
    expect(screen.getByRole('radio').elements()).toHaveLength(3)
    await expect
      .element(screen.getByRole('radio', { name: /Approve/ }))
      .toBeChecked()
    await expect.element(screen.getByText('Default')).toBeVisible()
    await expect
      .element(screen.getByText(/runs the deploy command with no human check/))
      .toBeVisible()
  })

  it('asks before turning on auto and saves only when confirmed', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='browser'
        branch='main'
        canEdit
        onChange={onChange}
      />
    )
    await screen.getByRole('radio', { name: /Auto/ }).click()
    const dialog = screen.getByRole('alertdialog')
    await expect.element(dialog).toBeVisible()
    expect(onChange).not.toHaveBeenCalled()
    await dialog.getByRole('button', { name: 'Turn on Auto' }).click()
    expect(onChange).toHaveBeenCalledWith('auto')
  })

  it('keeps the mode when the confirm is cancelled', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='browser'
        branch='main'
        canEdit
        onChange={onChange}
      />
    )
    await screen.getByRole('radio', { name: /Auto/ }).click()
    await screen.getByRole('button', { name: 'Cancel' }).click()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('saves manual straight away', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='browser'
        branch='main'
        canEdit
        onChange={onChange}
      />
    )
    await screen.getByRole('radio', { name: /Manual/ }).click()
    expect(onChange).toHaveBeenCalledWith('manual')
  })

  it('cannot be changed without edit rights', async () => {
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='browser'
        branch='main'
        canEdit={false}
        onChange={() => {}}
      />
    )
    await expect
      .element(screen.getByRole('radio', { name: /Manual/ }))
      .toBeDisabled()
  })
})

describe('MergePolicy with QA below Browser', () => {
  it('disables Auto and says why', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <MergePolicy
        value='approve'
        qaMode='gates'
        branch='main'
        canEdit
        onChange={onChange}
      />
    )
    const auto = screen.getByRole('radio', { name: /Auto/ })
    await expect.element(auto).toBeDisabled()
    await expect
      .element(screen.getByText(/Needs QA set to Browser/))
      .toBeVisible()
    await expect
      .element(screen.getByRole('radio', { name: /Manual/ }))
      .toBeEnabled()
  })

  it('keeps Auto selectable when it is already on', async () => {
    const screen = await render(
      <MergePolicy
        value='auto'
        qaMode='gates'
        branch='main'
        canEdit
        onChange={() => {}}
      />
    )
    await expect
      .element(screen.getByRole('radio', { name: /Auto/ }))
      .toBeEnabled()
    expect(screen.getByText(/Needs QA set to Browser/).elements()).toHaveLength(
      0
    )
  })
})

describe('QaModeControl', () => {
  it('offers three modes, each explained, with the current one checked', async () => {
    const screen = await render(
      <QaModeControl
        value='gates'
        mergeMode='approve'
        canEdit
        onChange={() => {}}
      />
    )
    expect(screen.getByRole('radio').elements()).toHaveLength(3)
    await expect
      .element(screen.getByRole('radio', { name: 'Gates only' }))
      .toBeChecked()
    await expect.element(screen.getByText(/^No checks\./)).toBeVisible()
    await expect
      .element(screen.getByText(/checks each acceptance criterion/))
      .toBeVisible()
  })

  it('saves the picked mode', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <QaModeControl
        value='gates'
        mergeMode='approve'
        canEdit
        onChange={onChange}
      />
    )
    await screen.getByRole('radio', { name: 'Browser' }).click()
    expect(onChange).toHaveBeenCalledWith('browser')
  })

  it('locks Off and Gates only while merge is Auto', async () => {
    const onChange = vi.fn()
    const screen = await render(
      <QaModeControl
        value='browser'
        mergeMode='auto'
        canEdit
        onChange={onChange}
      />
    )
    await expect
      .element(screen.getByRole('radio', { name: 'Off' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('radio', { name: 'Gates only' }))
      .toBeDisabled()
    await expect
      .element(screen.getByText(/Auto merge needs Browser/))
      .toBeVisible()
  })

  it("shows the server's refusal", async () => {
    const screen = await render(
      <QaModeControl
        value='gates'
        mergeMode='approve'
        canEdit
        error='Browser QA needs a runbook with a qa section.'
        onChange={() => {}}
      />
    )
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent('Browser QA needs a runbook with a qa section.')
  })

  it('cannot be changed without edit rights', async () => {
    const screen = await render(
      <QaModeControl
        value='gates'
        mergeMode='approve'
        canEdit={false}
        onChange={() => {}}
      />
    )
    await expect
      .element(screen.getByRole('radio', { name: 'Off' }))
      .toBeDisabled()
  })
})

describe('DeployCommand', () => {
  const base = {
    executor: 'local' as const,
    host: '',
    user: '',
    onSave: () => {},
  }

  it('shows members only whether a command is set', async () => {
    const screen = await render(
      <DeployCommand {...base} value={null} isSet canEdit={false} />
    )
    await expect
      .element(screen.getByText(/A deploy command is set/))
      .toBeVisible()
    expect(screen.getByRole('textbox').elements()).toHaveLength(0)
  })

  it('says when no command is set', async () => {
    const screen = await render(
      <DeployCommand {...base} value={null} isSet={false} canEdit={false} />
    )
    await expect
      .element(screen.getByText(/No deploy command is set/))
      .toBeVisible()
  })

  it('lets admins edit and save the command', async () => {
    const onSave = vi.fn()
    const screen = await render(
      <DeployCommand
        {...base}
        value='make deploy'
        isSet
        canEdit
        onSave={onSave}
      />
    )
    const box = screen.getByRole('textbox')
    await expect.element(box).toHaveValue('make deploy')
    await box.fill('make release')
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(onSave).toHaveBeenCalledWith('make release')
  })
})
