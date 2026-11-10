import { AxiosError, AxiosHeaders, type AxiosAdapter } from 'axios'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth-store'
import { api, apiErrorMessage, initials } from './client'
import type { AuthUser } from './types'

function errorWith(data: unknown, status = 400) {
  return new AxiosError('Request failed', String(status), undefined, null, {
    status,
    statusText: '',
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

describe('apiErrorMessage', () => {
  it('prefers Taiga _error_message', () => {
    expect(apiErrorMessage(errorWith({ _error_message: 'Nope' }))).toBe('Nope')
  })

  it('falls back to the first field error', () => {
    expect(
      apiErrorMessage(errorWith({ subject: ['This field is required.'] }))
    ).toBe('Subject: This field is required.')
  })

  it('names short fields in capitals', () => {
    expect(apiErrorMessage(errorWith({ url: ['Invalid value.'] }))).toBe(
      'URL: Invalid value.'
    )
  })

  it('uses the fallback for non-axios errors', () => {
    expect(apiErrorMessage(new Error('x'), 'Fallback')).toBe('Fallback')
  })
})

describe('initials', () => {
  it('takes up to two initials from names and usernames', () => {
    expect(initials('Arif Nurdiansyah')).toBe('AN')
    expect(initials('web.dev')).toBe('WD')
    expect(initials('admin')).toBe('A')
  })
})

describe('token refresh', () => {
  const user = { id: 6, username: 'webdev' } as AuthUser
  const originalAdapter = api.defaults.adapter

  beforeEach(() => {
    useAuthStore.getState().setSession({ token: 'old', refresh: 'r1', user })
  })

  afterEach(() => {
    api.defaults.adapter = originalAdapter
    useAuthStore.getState().reset()
  })

  it('refreshes once on 401 and retries with the new token', async () => {
    const seen: string[] = []
    let refreshCalls = 0
    const adapter: AxiosAdapter = async (config) => {
      if (config.url === '/auth/refresh') {
        refreshCalls++
        expect(config.headers.Authorization).toBeUndefined()
        expect(JSON.parse(config.data)).toEqual({ refresh: 'r1' })
        return {
          data: { auth_token: 'new', refresh: 'r2' },
          status: 200,
          statusText: '',
          headers: {},
          config,
        }
      }
      const auth = String(config.headers.Authorization)
      seen.push(auth)
      if (auth === 'Bearer old')
        throw new AxiosError('Unauthorized', '401', config, null, {
          status: 401,
          statusText: '',
          data: {},
          headers: {},
          config,
        })
      return {
        data: { ok: true },
        status: 200,
        statusText: '',
        headers: {},
        config,
      }
    }
    api.defaults.adapter = adapter

    const res = await api.get('/projects')

    expect(res.data).toEqual({ ok: true })
    expect(seen).toEqual(['Bearer old', 'Bearer new'])
    expect(refreshCalls).toBe(1)
    expect(useAuthStore.getState().session).toMatchObject({
      token: 'new',
      refresh: 'r2',
    })
  })
})
