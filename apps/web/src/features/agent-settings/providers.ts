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

export const selectClass =
  'h-9 w-full rounded-md border border-input bg-background px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-60'
