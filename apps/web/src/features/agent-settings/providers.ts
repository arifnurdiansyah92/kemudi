/** OpenAI-compatible providers. Brand names, the same in every language. */
export const PROVIDERS = [
  { id: 'sumopod', label: 'sumopod', url: 'https://ai.sumopod.com/v1' },
  { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com/v1' },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    url: 'https://openrouter.ai/api/v1',
  },
  { id: 'deepseek', label: 'DeepSeek', url: 'https://api.deepseek.com/v1' },
  { id: 'groq', label: 'Groq', url: 'https://api.groq.com/openai/v1' },
  {
    id: 'ollama',
    label: 'Ollama',
    url: 'http://host.docker.internal:11434/v1',
  },
] as const

export function providerOf(url: string) {
  const u = url.trim().replace(/\/+$/, '')
  return PROVIDERS.find((p) => p.url === u)?.id ?? null
}

export function hostOf(url: string) {
  try {
    return new URL(url.trim()).hostname
  } catch {
    return ''
  }
}

/** Hosts the client takes as private. The server has the last word (it
 * resolves names); a single-label name such as a Docker service is left to it. */
function privateHost(host: string) {
  const h = host.replace(/^\[|\]$/g, '').toLowerCase()
  if (h === 'localhost' || h === 'host.docker.internal' || h === '::1')
    return true
  if (!h.includes('.')) return true
  const ip = h.match(/^(\d+)\.(\d+)\.\d+\.\d+$/)
  if (!ip) return false
  const [a, b] = [Number(ip[1]), Number(ip[2])]
  return (
    a === 10 ||
    a === 127 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168)
  )
}

/** Plain http to what looks like a public address: the key and prompts
 * would travel unencrypted. */
export function isInsecureHttp(url: string) {
  const u = url.trim()
  if (!/^http:\/\//i.test(u)) return false
  const host = hostOf(u)
  return host !== '' && !privateHost(host)
}

/** The server's refusal of plain http to a public address (its own text). */
export const INSECURE_REFUSAL = 'allow unencrypted http'

export const selectClass =
  'h-9 w-full rounded-md border border-input bg-background px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-60'
