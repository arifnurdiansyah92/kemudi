# Awak dev loop: from request to tested branch

Status: iteration 1 design, 2026-11-13, revised after a three-member panel
(delivery process, agent security, QA automation). The user asked to start
without a Q&A round, so every choice not quoted from them is the builder's
call and is marked **(call)**.

## Intent

The user wants to manage Kemudi's own development in Kemudi:

> upload kontrak / prompting / break down kebutuhan user → otomatis jadi task →
> di-pickup Awak (Hermes agent) → commit → geser ke Ready for test → ada agent
> cek API dan Frontend → kirim bukti SS ke komentar → oke geser ke Done → ga
> oke balik ke In progress dan panggil Awak untuk kerjakan ulang.

It is a product, iterated. Iteration 1 must run the whole loop end to end and
be measured on a handful of small known stories, not polish any one stage.

**Success for iteration 1:** from a short text request, stories appear on the
board, and at least 3 of 5 seeded small frontend stories reach Done with a
commit on an `awak/us-<ref>` branch and a comment carrying per-criterion
results and screenshots. We record pass rate, attempts, time and cost.

## Non-goals (iteration 1)

- Merging to `main`, pushing to GitHub, opening PRs. A human reviews and
  merges `awak/*` branches. **Done means "QA passed", not "shipped"**: QA-passed
  stories also get the tag `awaiting-merge`, and the comment says the branch is
  not merged. **(call)** The user named Done as the target column; the tag
  keeps the board honest.
- Stories that need `services/kemudi-back` changes (no per-branch backend).
  Intake sends them to New with a comment instead of Ready. API checks in QA
  run against the current dev stack.
- Document upload in the web UI and an Awak page in apps/web (iteration 2).
  Intake is text or a file through the API and CLI.
- Webhooks (polling instead; webhooks are off in kemudi-back). Parallel jobs
  (one story at a time; low-memory machine).

## Anti-goals

- Awak writing anywhere but `awak/us-<ref>` branches.
- Secrets (LLM key, Taiga passwords or tokens) reaching the agent, a commit,
  a comment or an attachment.
- A story looping forever, or infra flakiness burning a story's attempts.
- Silent failure: every stop leaves a comment saying why.
- Any write to a Taiga that is not the local dev stack.

## Shape

```
PM ─intake (text/file)─▶ orchestrator ─▶ stories: Ready + agent-ready
                                           (too big / backend → New + comment)
worker (poll 20 s, one job at a time)
  claim → In progress, assign awak, comment "attempt n/3 mulai"
  prepare  (orchestrator) sync main into its bare repo, fresh clone into
           /workspace/us-<ref>, branch awak/us-<ref>
  install  (runner) pnpm install --frozen-lockfile --ignore-scripts
  code     (kemudi-awak, Hermes coding prompt) edits + commits
  collect  (runner) commit leftovers; (orchestrator, hardened git) fetch the
           branch into its bare repo, require a new commit, secret-scan the diff
  gates    (runner) tsc -b, eslint, vitest, vite build ─ fail → rework
  → Ready for test, comment (branch, sha, gate results)
  qa-spec  (kemudi-awak, QA prompt, fresh clone, criteria only) writes a
           Playwright spec, one test per criterion
  qa-run   (runner) vite --strictPort on the branch, orchestrator's Playwright
           config, token-seeded session, screenshot per test, run twice
  verdict  from exit codes, not from the model
     pass ─▶ Done + awaiting-merge, comment with per-criterion table + images
     fail ─▶ In progress, comment with failures; next attempt gets them
     infra error (timeout, install, server, flaky) ─▶ retry with backoff,
           not counted; 3 infra errors → blocked
  after 3 failed attempts ─▶ blocked flag with reason, tag needs-human,
           assign to the story's owner
```

### Containers and networks **(call)**, from the security review

- **kemudi-sandbox** network, `internal: true` (no internet): kemudi-awak,
  kemudi-runner, kemudi-llm-proxy, kemudi-gateway, kemudi-orchestrator.
- **kemudi-awak**: Hermes from the existing image, own managed config
  (`infra/awak/config.yaml`): toolsets `terminal`, `file`; approvals off,
  unattended approve; `max_turns` 60; memory, skills, plugins, MCP, web off.
  Model base URL is kemudi-llm-proxy, with a dummy key. It holds **no
  secrets**. Non-root, `cap_drop: ALL`, `no-new-privileges`, memory and pid
  limits. Its API key (`KEMUDI_AWAK_API_KEY`) only guards its own port.
- **kemudi-llm-proxy**: nginx on kemudi-sandbox and the default network. It
  forwards only `/v1/chat/completions` and `/v1/models` to the provider and
  adds the provider key. Agents never see the key.
- **kemudi-runner**: a small HTTP service (Python stdlib) in an image built
  from the Hermes image (node, git, Chromium) plus `@playwright/test`. It
  runs a fixed set of commands in `/workspace/us-<ref>`: install, commit
  leftovers, gates, QA spec run. It holds no secrets; it is also on an egress
  network for npm. A QA token arrives per request, is written outside the
  workspace, and is deleted after the run.
- **kemudi-orchestrator** owns the bare repo (`/var/lib/kemudi-ai/awak.git`)
  and the host repo's git dir mounted at `/host-git`. It never runs git
  inside an agent-written repo except `fetch` with `core.hooksPath=/dev/null`
  and `core.fsmonitor=false`. It pushes to `/host-git` only refs matching
  `^refs/heads/awak/us-\d+$`.

### Taiga side

- Dogfood project `kemudi` on the local stack (scrum template statuses New,
  Ready, In progress, Ready for test, Done). A story is Awak's when tagged
  `agent-ready` and in Ready.
- Bot user `awak` (member of `kemudi`): the orchestrator acts as it.
- QA user `awak-qa`, admin of a separate throwaway project `awak-qa-sandbox`
  only, so QA can create and edit things without touching the dogfood board.
  The orchestrator logs it in and hands the runner a token; the model never
  sees it.
- The worker refuses to start unless the Taiga URL host is `kemudi-back`,
  `kemudi-gateway`, `localhost` or `127.0.0.1`.

### Human control

- Before every transition the worker re-reads the story. If a human moved it,
  removed `agent-ready` or set it blocked, the job stops with a comment.
- A human moving a story from Ready for test or Done back to In progress (tag
  still on) starts a rework attempt; the human's latest comment is the
  feedback.
- Every comment carries attempt n/3, elapsed time and model cost so far.

### Intake

One LLM call (purpose `awak.intake`) turns text, or text extracted from a
PDF/DOCX, into stories: subject, description, 1 to 4 acceptance criteria,
`area` (`web`, `backend`, `both`). Only `web` stories with at most 4 criteria
go to Ready; the rest go to New with a comment saying why. **(call)** The user
said "otomatis jadi task"; small frontend stories flow straight on, the rest
wait for a PM.

### Rules

- Verdicts: QA pass requires both spec runs to pass every test, one test per
  criterion, and a valid screenshot per test. Disagreement between runs is an
  infra error (flaky), not a fail.
- Screenshots uploaded only from `/workspace/us-<ref>/.qa/results/`, real
  path checked, no symlinks, PNG magic bytes, under 5 MB.
- Secret scan (the values of sensitive env vars in the orchestrator, plus
  key-shaped patterns) on the diff before pushing and on every comment before
  posting. A hit fails the attempt with a comment that names the file, never
  the value.
- Every Hermes call is logged in `ai_calls` (`awak.intake`, `awak.code`,
  `awak.qa`); job steps in append-only `awak_events`.
- Comments in Indonesian, short.
- Models: `KEMUDI_AWAK_MODEL`, `KEMUDI_QA_MODEL`, default `deepseek-flash`
  (the user's cost preference). **(call)** `deepseek-v4-pro` or
  `seed-2-0-code` are config changes if quality is too low.

## Left to the builder

Prompt wording, poll and backoff details, runner API shape, Playwright config
details, test doubles.
