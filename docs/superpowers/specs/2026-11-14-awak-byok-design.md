# Awak BYOK: bring your own model key, global and per agent

Status: design, 2026-11-14. It builds on
`2026-11-14-awak-project-setup-design.md`. The user opted out of a Q&A round;
anything not quoted from them is the builder's call and is marked **(call)**.

## Intent

> "Tambah fitur agar bisa BYOK untuk agen, ada global setting ada per agent
> setting... hirarkinya agent setting > global setting"

Each Kemudi customer brings their own model provider account. Within one
project they may also want different agents on different providers or keys,
for example a strong coding model for Backend and a cheap one for QA.

## Behaviour

- **Three levels.** Each one either supplies a full model connection
  (`base_url`, `api_key`, `model`) or inherits from the level below it.
  1. **Agent (role) setting.** This is Project settings → Agent → Roles → a
     role's "Model connection" section.
  2. **Global setting.** This is a project-wide default for all of the
     project's agents, under Project settings → Agent → "Model connection
     (all agents)". **(call)** "Global" is read as project-wide because every
     other Awak setting is per project and is edited by project admins.
     An instance-wide level is the server default below.
  3. **Kemudi server default.** These are today's environment values
     (`KEMUDI_AI_BASE_URL`, `KEMUDI_AI_API_KEY`, `KEMUDI_AWAK_MODEL`), used
     when neither level above is set.
- **Precedence: agent > global > server default.** It is resolved per field
  group, not field by field: a level that sets a key sets its own base URL and
  model too. **(call)** Mixing a key from one level with a URL from another
  would send a key to the wrong provider.
- **Provider type: OpenAI-compatible chat completions.** This covers
  sumopod, OpenAI, OpenRouter, DeepSeek, Groq, local vLLM and Ollama. Hermes
  speaks this protocol. Native Anthropic or Gemini APIs come later, if needed.
- **Test connection.** It sends a 1-token chat completion with the resolved
  settings and reports ok/error and latency, without exposing the key.
- **Visibility of the resolved connection.** Each role shows which level its
  connection comes from ("From this agent", "From project default" or "Kemudi
  server default"), plus the model and base URL host.

## Security (unchanged boundary)

- **Keys stay out of Awak.** Awak never holds a key. The orchestrator becomes
  the model proxy on the internal network: Hermes in `kemudi-awak` calls
  `http://kemudi-orchestrator:8700/llm/v1/...` with a per-run alias as the
  model name (`awak-run-<random>`). The orchestrator maps the alias to the
  resolved connection, swaps in the real model and key, and forwards the
  request, streaming included.
  - Aliases expire when the run ends, and an unknown alias gets a 403.
  - `kemudi-llm-proxy` stays only as the path to the server default.
    **(call)** Simpler still is to route everything through the
    orchestrator and drop it. The builder decides and states which.
- **Key storage.**
  - Keys are encrypted at rest with Fernet (`KEMUDI_SECRET_KEY`).
  - They are write-only in the API: responses show `key_set` and the last 4
    characters.
  - They are never logged, never put in a prompt or comment, and never
    returned.
  - They are added to the secret-scan values used on diffs and comments.
- **Base URL.** It must be `https://`, or `http://` to a private or loopback
  address for self-hosted models. **(call)** No redirects are followed.
  Request timeouts match today's.
- **Cost logging.** `ai_calls` records the level and the model actually used
  for each call, but never the key.

## API (orchestrator)

- `GET/PUT /projects/{slug}/agent/llm` (global). The body is `{base_url,
  model, api_key?}`; an empty `api_key` keeps the current one, and an
  explicit `clear: true` removes the level.
- `GET/PUT /projects/{slug}/agent/roles/{id}/llm`, same shape (agent level).
- `POST .../llm/test` at both levels.
- `GET /projects/{slug}/agent/roles` gains `llm_source`
  (`agent|project|server`), `llm_model` and `llm_host`.
- Writes require project admin; reads require membership. A key is never
  returned.

## UI (apps/web)

Run the impeccable skill.

- **Project settings → Agent.** A new section, "Model connection (all
  agents)", sits after Merge policy. It has base URL, model, a write-only key
  field ("•••• 1a2b — replace"), Test connection and Clear.
- **Role editor.** A "Model connection" block with a "Use project default"
  toggle. When off, it shows the same fields as the global section. Each role
  row shows its source and model.
- Strings go in the `agent` namespace, en and id.

## Not in scope

Per-user keys, usage quotas per key, and non-OpenAI-compatible providers.
