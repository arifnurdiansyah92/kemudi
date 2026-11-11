# Contract Baseline Backtest POC: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the CR check on the pilot project's history. The SPK becomes a
baseline the PM approves. Each warranty-period request is classified against
that baseline, and the results are scored against the PM's answer key. This
works both from a CLI and from a Contract tab in `apps/web`.

**Architecture:**
- `apps/orchestrator` is a new Python service. It holds the contract data in
  SQLite for the POC and calls Hermes, which forwards to the model.
- `kemudi-back` is not changed.
- The web UI reaches the orchestrator at `/api/kemudi/*` through the dev
  gateway and the Vite proxy, using the user's Taiga token.

**Tech Stack:**
- Python 3.12, FastAPI, SQLAlchemy 2, pydantic 2, pypdf, python-docx, httpx,
  pytest. Packages are managed with uv.
- The web side is React 19 with TanStack Query and i18next, as `apps/web`
  already uses.

**Spec:** `docs/superpowers/specs/2026-11-11-contract-baseline-cr-design.md`

## Global Constraints

- **AI calls go only through Hermes.** Every call is OpenAI-compatible
  `POST {KEMUDI_HERMES_URL}/chat/completions` with
  `Authorization: Bearer {KEMUDI_HERMES_API_KEY}` and model `KEMUDI_AI_MODEL`
  (default `deepseek-flash`). Never call the provider directly.
- **No secrets in git.** `infra/.env` holds the keys.
- **Confidential data stays out of git.** Contract files, the dataset and the
  database live under `apps/orchestrator/data/`, which is gitignored.
- **AI only proposes; a PM decides.** Every AI call and every PM decision is
  stored in append-only tables (`ai_calls`, `decisions`). No endpoint updates
  or deletes them.
- **Labels are exactly** `in_baseline`, `cr_candidate` and
  `needs_clarification`.
- **Effort is in person-days per role.** Price in IDR is the sum of days ×
  rate-card rate. Story points are not used.
- **Language.** Stored AI text uses the project's working language (`id` by
  default). The UI is bilingual: there are no literal strings (lint enforces
  this), and the `id` and `en` locale keys must match.
- **License.** New code is AGPL-3.0-or-later, consistent with `apps/`.

## Review Focus

1. **Bad model output.** The model may return invalid or partial JSON, or a
   label outside the three allowed. Expect one retry, then the ticket is
   stored as `error` with the raw text. The run must not crash, and the
   ticket counts as wrong in the metrics.
2. **OCR noise in the SPK.** "lntegrasi", a total line glued to its label
   and module rows split across a page break must still produce sections that
   cite the right module.
3. **Hermes unreachable or timing out mid-run.** Expect a clear error. Results
   already finished are kept, and re-running finishes only the missing
   tickets.
4. **A PM who isn't an admin calling approve or verdict endpoints.** Expect
   403. An expired or absent Taiga token gets 401.
5. **Metrics with no verdicts yet, or with an empty category.** Expect no
   division by zero. Accuracy is shown as "—", not NaN.

---

## File structure

```
apps/orchestrator/
  pyproject.toml            # deps, pytest config
  Dockerfile
  README.md
  kemudi_ai/
    __init__.py
    config.py               # Settings from env
    llm.py                  # Hermes client, JSON calls, audit record
    documents.py            # PDF/DOCX → sections
    baseline.py             # sections → draft baseline items
    classify.py             # ticket × baseline → classification
    pricing.py              # rate card maths
    store.py                # SQLAlchemy models + session
    backtest.py             # run + metrics
    auth.py                 # Taiga token → user, project role
    api.py                  # FastAPI app
    __main__.py             # CLI: extract | baseline | backtest
  tests/                    # pytest, FakeLLM, fixtures (synthetic SPK text)
infra/docker-compose.dev.yml  # + kemudi-orchestrator
infra/gateway/kemudi.conf     # + /api/kemudi/ → orchestrator
apps/web/vite.config.ts       # + /api/kemudi proxy (before /api)
apps/web/src/lib/kemudi-ai/   # client + queries
apps/web/src/features/contract/  # Contract tab screens
apps/web/src/routes/_authenticated/p/$slug/contract.tsx
apps/web/src/locales/{en,id}/contract.json
```

---

### Task 1: Orchestrator skeleton, config, store

**Files:**
- Create: `apps/orchestrator/pyproject.toml`
- Create: `apps/orchestrator/kemudi_ai/{__init__,config,store}.py`
- Test: `apps/orchestrator/tests/test_store.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings), with these fields:
  - `hermes_url: str` (env `KEMUDI_HERMES_URL`, default `http://localhost:8642/v1`)
  - `hermes_api_key: str` (env `KEMUDI_HERMES_API_KEY`)
  - `model: str` (env `KEMUDI_AI_MODEL`, default `deepseek-flash`)
  - `db_url: str` (env `KEMUDI_AI_DB_URL`, default `sqlite:///data/kemudi-ai.db`)
  - `taiga_api_url: str` (env `KEMUDI_TAIGA_API_URL`, default `http://localhost:9100/api/v1`)
  - `token_price_idr_per_1k: float` (default `0.0`)
  - `get_settings()`
- Produces: `store.py`, with these models:
  - `Contract(id, project_slug unique, filename, sections JSON, lang str='id', rate_card JSON, created_at)`
  - `BaselineVersion(id, contract_id, number int, status 'draft'|'approved', items JSON, approved_by str|None, approved_at|None)`
  - `BacktestRun(id, contract_id, baseline_version_id, dataset_name, started_at, finished_at|None)`
  - `BacktestResult(id, run_id, ticket_id, source, text, expected JSON, predicted JSON|None, status 'ok'|'error', verdict 'right'|'wrong'|None)`
  - `AiCall(id, at, purpose, model, prompt TEXT, response TEXT, prompt_tokens, completion_tokens, latency_ms, cost_idr)`
  - `Decision(id, at, actor, action, subject, detail JSON)`
  - `make_session(db_url) -> sessionmaker`
  - `init_db(engine)`

- [ ] **Step 1: Write the failing test.**
  - `test_roundtrip_contract_and_baseline`: create a Contract and a draft
    BaselineVersion with 2 items, read them back, and assert both items and
    `status=='draft'`.
  - `test_ai_calls_append_only`: assert the module has no update or delete
    helpers. The check is a convention test on `store.__all__` exposing only
    `record_ai_call` and `record_decision` writers for these tables.
- [ ] **Step 2: Run.** `cd apps/orchestrator && uv run pytest tests/test_store.py -v`
  should FAIL (import error).
- [ ] **Step 3: Implement.** Write `config.py` and `store.py`, plus
  `record_ai_call(session, **fields) -> AiCall` and
  `record_decision(session, actor, action, subject, detail) -> Decision`.
- [ ] **Step 4: Run.** The tests should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): service skeleton and store`

### Task 2: Hermes client with JSON calls and audit

**Files:**
- Create: `apps/orchestrator/kemudi_ai/llm.py`
- Test: `apps/orchestrator/tests/test_llm.py` (uses `httpx.MockTransport`)

**Interfaces:**
- Produces: `class LLM(Protocol): def json(self, purpose: str, system: str, user: str) -> dict`
- Produces: `HermesLLM(settings, session_factory)`. It implements `LLM`: it
  posts with `response_format={"type":"json_object"}` and `temperature=0`,
  then parses the first JSON object in the content (tolerating code fences).
  On a parse failure it retries once with a corrective user message.
  - Every attempt calls `record_ai_call`, with
    `cost_idr = (prompt+completion)/1000 × token_price_idr_per_1k`.
  - If it still fails, it raises `LLMError(raw: str)`.
  - Timeout is 120 s.
- Produces: `FakeLLM(responses: dict[str, list[dict|str]])` in
  `tests/fakes.py`, for the other tasks.

- [ ] **Step 1: Write the failing tests.**
  - `test_parses_fenced_json` (content ```` ```json {"a":1}``` ```` → `{"a":1}`).
  - `test_retries_once_then_raises` (two invalid replies → `LLMError`, 2 AiCall rows).
  - `test_records_tokens_and_latency` (usage `{prompt_tokens:10, completion_tokens:5}` → row fields set).
- [ ] **Step 2: Run.** `uv run pytest tests/test_llm.py -v` should FAIL.
- [ ] **Step 3: Implement** `llm.py`.
- [ ] **Step 4: Run.** The tests should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): Hermes JSON client with audit log`

### Task 3: Document extraction (PDF/DOCX → sections)

**Files:**
- Create: `apps/orchestrator/kemudi_ai/documents.py`
- Test: `apps/orchestrator/tests/test_documents.py`, with
  `tests/fixtures/spk_text.txt` (synthetic SPK-like text carrying the same
  OCR noise; not the real SPK)

**Interfaces:**
- Produces: `Section(ref: str, title: str, text: str)` (pydantic).
- Produces: `extract_text(filename: str, data: bytes) -> str`. It uses pypdf
  for PDFs, python-docx for DOCX, and raises `ValueError` for anything else.
- Produces: `normalize(text: str) -> str`. It fixes common OCR confusions:
  `\bl(?=[A-Z][a-z])` → `I` (lntegrasi→Integrasi, lnventori→Inventori),
  `Tennin`→`Termin`, collapsed whitespace and hyphenated line breaks.
- Produces: `split_sections(text: str) -> list[Section]`. It splits on known
  upper-case headings (`RUANG LINGKUP PEKERJAAN`, `NILAI PEKERJAAN`,
  `JANGKA WAKTU`, `HAK DAN KEWAJIBAN`, `KETENTUAN TAMBAHAN`, `PENUTUP`, and
  generic all-caps lines ≥ 2 words) and numbers them `S1..Sn`. Text with no
  headings becomes one section, `S1`.
- Produces: `extract_sections(filename, data) -> list[Section]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_normalize_fixes_ocr` (`"lntegrasi Payment"` → `"Integrasi Payment"`; `"Tennin 2"` → `"Termin 2"`).
  - `test_split_finds_scope_and_terms` (the fixture gives sections whose
    titles include `RUANG LINGKUP PEKERJAAN` and `KETENTUAN TAMBAHAN`, and
    the KETENTUAN text contains `Change Request`).
  - `test_rejects_unknown_type`.
- [ ] **Step 2: Run.** It should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** It should PASS. Also run once against the real file:
  `uv run python -m kemudi_ai extract data/pilot/contract.pdf` should print
  ≥ 5 sections, with module names readable.
- [ ] **Step 5: Commit.** `feat(orchestrator): contract text extraction`

### Task 4: Draft baseline from sections

**Files:**
- Create: `apps/orchestrator/kemudi_ai/baseline.py`, `kemudi_ai/pricing.py`
- Test: `apps/orchestrator/tests/test_baseline.py`

**Interfaces:**
- Produces: `BaselineItem` (pydantic), with these fields:
  - `ref: str` (`B1..Bn`)
  - `kind: Literal['epic','story','obligation','term']`
  - `title: str`
  - `description: str`
  - `acceptance: list[str]`
  - `clauses: list[str]` (section refs like `S2`, plus the quoted module or
    clause name)
  - `price_idr: int|None` (the contract price, when the SPK gives one)

  `obligation` and `term` capture things like "bug fixes during warranty are
  in scope" and "CR outside SPK is billed": the classifier needs both.
- Produces: `draft_baseline(llm: LLM, sections: list[Section], lang: str) -> list[BaselineItem]`.
  - It makes one LLM call, purpose `baseline`.
  - The system prompt (Indonesian when `lang=='id'`) asks for every module as
    an epic, every listed feature as a story, every party obligation and
    every additional term as an obligation/term item, with clauses cited.
  - It validates the result with pydantic and renumbers the refs.
- Produces, in `pricing.py`:
  - `RateCard(currency='IDR', per_day: dict[str,int])`
  - `price(effort_days: dict[str,float], rc: RateCard) -> int` (an unknown
    role raises `KeyError` naming the role)

- [ ] **Step 1: Write the failing tests.**
  - `test_draft_validates_and_renumbers`: FakeLLM returns 3 items with refs
    `x`, `y`, `z`; the result has refs `B1..B3` and kinds preserved.
  - `test_draft_rejects_items_without_clauses`: an item with empty
    `clauses` is dropped and logged.
  - `test_price_sums_roles`: `{"backend":2,"qa":0.5}` with backend
    1_500_000 and qa 1_000_000 gives `3_500_000`.
- [ ] **Step 2: Run.** It should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** It should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): draft baseline from contract sections`

### Task 5: Classify a ticket against the baseline

**Files:**
- Create: `apps/orchestrator/kemudi_ai/classify.py`
- Test: `apps/orchestrator/tests/test_classify.py`

**Interfaces:**
- Consumes: `BaselineItem`, `RateCard`, `price`, `LLM`.
- Produces: `Classification` (pydantic), with these fields:
  - `label: Literal['in_baseline','cr_candidate','needs_clarification']`
  - `reason: str`
  - `clause: str` (a baseline ref plus a quote)
  - `effort_days: dict[str,float]` (`{}` for `in_baseline`)
  - `price_idr: int` (computed with `price()`, never taken from the model)
  - `question: str|None` (what to ask the client, for `needs_clarification`)
- Produces: `classify(llm, ticket_text: str, baseline: list[BaselineItem], rc: RateCard, lang: str) -> Classification`.
  - It makes one call, purpose `classify`.
  - The prompt carries the whole baseline as compact lines
    (`B3 [story] Integrasi Payment Gateway (VA/QRIS) — S2`) and the
    rate-card roles.
  - The prompt states the rules:
    - Defects in delivered features during warranty are `in_baseline`.
    - New behaviour, data, jobs or screens not in the baseline are
      `cr_candidate`.
    - If the answer depends on detail the contract doesn't specify, the
      label is `needs_clarification`, and the reply must say what to ask.
  - If `label=='in_baseline'`, any effort the model returns is cleared.

- [ ] **Step 1: Write the failing tests.**
  - `test_price_computed_not_trusted` (the model says `price_idr: 1`; the
    result is the rate-card sum).
  - `test_in_baseline_clears_effort`.
  - `test_invalid_label_raises_llmerror`.
  - `test_unknown_role_in_effort_maps_to_error`.
- [ ] **Step 2: Run.** It should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** It should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): classify tickets against the baseline`

### Task 6: Backtest run, resume, metrics, CLI

**Files:**
- Create: `apps/orchestrator/kemudi_ai/backtest.py`, `kemudi_ai/__main__.py`
- Test: `apps/orchestrator/tests/test_backtest.py`

**Interfaces:**
- Consumes: the dataset JSON at
  `data/pilot/backtest.json`, shaped
  `{project, contract_file, rate_card{currency, per_day}, tickets[{id, source, date, text, expected{label, reason, clause, effort_days, price_idr, waived}}]}`.
- Produces: `run_backtest(session, llm, contract: Contract, baseline: BaselineVersion, dataset: dict, run: BacktestRun|None=None) -> BacktestRun`.
  - It skips tickets that already have an `ok` result in `run`, which is
    how a run resumes.
  - An `LLMError` stores the ticket as `status='error'`, and the loop goes on.
- Produces: `metrics(results: list[BacktestResult]) -> Metrics`, with these fields:
  - `total`
  - `accuracy: float|None`
  - `per_label: dict[label, {expected, predicted, correct}]`
  - `confusion: dict[expected, dict[predicted, int]]`
  - `cr_recall: float|None`. This counts expected `cr_candidate`
    predicted as `cr_candidate` or `needs_clarification`, since both stop the
    work before it starts.
  - `false_cr_rate: float|None`. This counts expected `in_baseline`
    predicted as `cr_candidate`.
  - `value_expected_idr`, `value_predicted_idr`. Waived items count at their
    listed price.
  - `verdicts: {right, wrong, pending}`
  - Errors count as wrong. Any ratio with a zero denominator is `None`.
- Produces: the CLI.
  - `python -m kemudi_ai extract <file>`
  - `python -m kemudi_ai baseline <project_slug> <file> [--lang id]`
    creates a Contract and a draft BaselineVersion.
  - `python -m kemudi_ai approve <project_slug> --by <name>`
  - `python -m kemudi_ai backtest <project_slug> <dataset.json>` prints
    the metrics table.

- [ ] **Step 1: Write the failing tests.**
  - `test_resume_skips_done` (2 tickets, the first done; FakeLLM is called once).
  - `test_error_counts_wrong`.
  - `test_metrics_empty_is_none` (no results → `accuracy is None`).
  - `test_cr_recall_counts_clarification_as_caught`.
- [ ] **Step 2: Run.** It should FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** It should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): backtest runner, metrics and CLI`

### Task 7: HTTP API with Taiga auth

**Files:**
- Create: `apps/orchestrator/kemudi_ai/{auth,api}.py`
- Test: `apps/orchestrator/tests/test_api.py` (FastAPI TestClient; Taiga
  mocked with `httpx.MockTransport`)

**Interfaces:**
- Produces: `current_user(authorization header) -> TaigaUser(id, username, full_name)`.
  It calls `GET {taiga_api_url}/users/me` and returns 401 when the call fails.
- Produces: `require_admin(slug, token) -> None`. It calls
  `GET /projects/by_slug?slug=` and returns 403 unless `i_am_admin`.
- Produces: these routes, all under `/api/kemudi`, all JSON. Every
  member-readable route requires a valid token; mutations require admin.

  | Route | Who | Does |
  | --- | --- | --- |
  | `GET /projects/{slug}/contract` | member | Returns `{contract|null, baseline: {draft|null, approved|null, history[]}, runs[]}` |
  | `POST /projects/{slug}/contract` | admin | Multipart `file`, `lang`, `rate_card` (JSON). Extracts the sections and stores the contract |
  | `POST /projects/{slug}/baseline/draft` | admin | Runs `draft_baseline` and stores the draft |
  | `PUT /projects/{slug}/baseline/draft` | admin | Body `{items}`. The PM's edits; records a Decision |
  | `POST /projects/{slug}/baseline/approve` | admin | The draft becomes approved version n+1; records a Decision |
  | `POST /projects/{slug}/backtests` | admin | Multipart `dataset` JSON. Runs in a background task and returns `{run_id}` |
  | `GET /projects/{slug}/backtests/{run_id}` | member | Returns `{run, results[], metrics}` |
  | `PUT /projects/{slug}/backtests/{run_id}/results/{result_id}/verdict` | admin | Body `{verdict}`; records a Decision |
  | `GET /health` | anyone | Health check |

- [ ] **Step 1: Write the failing tests.**
  - `test_401_without_token`.
  - `test_403_member_cannot_approve`.
  - `test_approve_bumps_version_and_logs_decision`.
  - `test_verdict_updates_metrics`.
  - `test_backtest_run_returns_results_after_background` (FakeLLM injected
    via a dependency override).
- [ ] **Step 2: Run.** It should FAIL.
- [ ] **Step 3: Implement.** Inject the LLM through `Depends(get_llm)` so tests
  can override it.
- [ ] **Step 4: Run.** It should PASS.
- [ ] **Step 5: Commit.** `feat(orchestrator): HTTP API with Taiga auth`

### Task 8: Wire into the dev stack

**Files:**
- Create: `apps/orchestrator/Dockerfile` (python:3.12-slim, uv sync, `uvicorn kemudi_ai.api:app --host 0.0.0.0 --port 8700`)
- Create: `apps/orchestrator/README.md` (replacing the "not started" stub)
- Modify: `infra/docker-compose.dev.yml`. Add `kemudi-orchestrator`
  with env `KEMUDI_HERMES_URL=http://kemudi-hermes:8642/v1`,
  `KEMUDI_HERMES_API_KEY`, `KEMUDI_AI_MODEL`,
  `KEMUDI_TAIGA_API_URL=http://kemudi-back:8000/api/v1`, and a bind mount
  of `../apps/orchestrator/data:/app/data`.
- Modify: `infra/gateway/kemudi.conf`. Add `location /api/kemudi/`,
  placed before `/api/`, that proxies to `kemudi-orchestrator:8700`.
- Modify: `apps/web/vite.config.ts`. Add `'/api/kemudi'` to
  `env.KEMUDI_ORCHESTRATOR ?? 'http://localhost:8700'`, ahead of `/api`.

- [ ] **Step 1:** `docker compose -f infra/docker-compose.dev.yml --env-file infra/.env up -d --build kemudi-orchestrator kemudi-gateway`
- [ ] **Step 2: Verify.** `curl localhost:9100/api/kemudi/health` should return `{"ok":true}`, and
  `curl localhost:9100/api/kemudi/projects/x/contract` should return 401.
- [ ] **Step 3: Commit.** `feat(infra): orchestrator in the dev stack`

### Task 9: Contract tab in apps/web

**Files:**
- Create: `apps/web/src/lib/kemudi-ai/{client,queries}.ts`. This is a fetch
  wrapper using the Taiga token from the auth store, plus hooks:
  - `useContract(slug)`, `useUploadContract(slug)`
  - `useDraftBaseline(slug)`, `useSaveDraft(slug)`, `useApproveBaseline(slug)`
  - `useStartBacktest(slug)`, `useBacktest(slug, runId)` (polls every 3 s
    while `finished_at` is null)
  - `useSetVerdict(slug, runId)`
- Create: `apps/web/src/features/contract/{index,contract-upload,baseline-review,backtest-report}.tsx`
- Create: `apps/web/src/routes/_authenticated/p/$slug/contract.tsx`
- Create: `apps/web/src/locales/{en,id}/contract.json`, and register the
  namespace in `src/i18n/resources.ts`.
- Modify: `apps/web/src/components/layout/use-nav-groups.ts`. Add a
  "Contract" / "Kontrak" project nav item (lucide `FileSignature`).
- Test: `apps/web/src/features/contract/backtest-report.test.tsx`

**Behaviour:**
- **Upload.** File input (PDF/DOCX), language select, and a rate-card editor
  with one row per role and IDR per day (formatted with `useFormat().rupiah`).
  The extracted sections are listed below.
- **Baseline review.** A table of items grouped by kind. Title, description
  and acceptance can be edited inline. The clause refs appear as chips; on
  hover they show the section text. Buttons: "Generate draft", "Save",
  "Approve baseline" (admin only, with a confirm dialog). The approved
  version and the version history are read-only.
- **Backtest report.**
  - A start button and a dataset file input.
  - A metrics row: accuracy, CR caught, false CR, value found vs the PM's
    value in Rupiah.
  - A confusion table.
  - A results table: ticket text, expected vs predicted label (as chips;
    meaning-only colour per `DESIGN.md`), reason, clause, effort, price, and
    a ✓/✗ verdict.
  - AI text is labelled as a suggestion.
- **Copy.**
  - The labels are "Sesuai baseline" / "In baseline", "Kandidat CR" /
    "CR candidate", "Perlu klarifikasi" / "Needs clarification".
  - Empty states explain the next step.

- [ ] **Step 1: Write the failing test.** `backtest-report.test.tsx`
  renders `BacktestReport` with fixture data (3 results, 1 verdict) and
  asserts:
  - the accuracy text;
  - the "—" shown when there are no verdicts;
  - the verdict button calls `onVerdict(resultId, 'right')`.
- [ ] **Step 2: Run.** `pnpm vitest run --browser.headless src/features/contract` should FAIL.
- [ ] **Step 3: Implement** the screens, route, nav and locales.
- [ ] **Step 4: Run.** `pnpm lint && pnpm typecheck && pnpm vitest run --browser.headless` should PASS.
- [ ] **Step 5: Commit.** `feat(web): Contract tab with baseline review and backtest report`

### Task 10: Run the real backtest and report

- [ ] **Step 1:** Through the UI on the `kemudi-demo` project, or with the CLI
  as fallback:
  1. Upload `spk.pdf`.
  2. Generate the draft.
  3. Approve.
  4. Run the backtest with `data/pilot/backtest.json`.
- [ ] **Step 2:** Mark verdicts by comparing with the answer key. The CLI
  `backtest` output already computes agreement with `expected`. The verdicts
  in the UI are the PM's own check.
- [ ] **Step 3:** Screenshot the Contract tab in ID and EN, then write the
  results to `docs/poc/2026-11-pilot-backtest.md`. That file holds
  numbers only; it contains no SPK text or prices beyond aggregate figures,
  since the details are confidential.
- [ ] **Step 4: Commit and push.** Update tracker story #28.
