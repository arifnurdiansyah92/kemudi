# Contract baseline and Change Requests (Differentiator 1, MVP)

Date: 2026-11-11
Source: "BRD — Diferensiator Kemudi" v0.1 (Claude Doc), section 5, BR-1.1 to BR-1.5.
Status: draft for review

## Why

Vendors lose margin when work outside the SOW gets done without a Change
Request. Jira and Linear have no notion of a contract, so they can't catch it.
Kemudi turns the SOW into a locked baseline and checks every new ticket
against it, so out-of-scope work is caught before anyone builds it.

This is the BRD's kill test: if, after 2 to 3 sprints on an internal project,
the CR check hasn't found billable work or stopped unpaid out-of-scope work,
Differentiator 1 is weak and the positioning gets revisited. The slice has to
be good enough to run that test honestly, and nothing more.

## POC first: a backtest on the pilot project (user's decision, 2026-11-11)

Before any of the live flow below, the CR check is proven on history.

1. **Baseline from the SOW.** The pilot's SOW is turned into a baseline using
   goals 1 and 2 below. The baseline is stored as **a separate reference
   list**. It is **not** created as Taiga epics or stories, so nothing is
   duplicated, and existing tickets don't have to be linked to it.
2. **Reclassify the warranty-period tickets.** The CR check reclassifies the
   full history of tickets from the pilot's warranty period against that
   baseline. Each ticket gets a label, a reason, the SOW clause it relies on
   and, for CR candidates, an effort estimate.
3. **Backtest report.** One report shows, per label:
   - how many tickets got that label;
   - the estimated effort of the CR candidates, in person-days and in Rupiah;
   - the tickets themselves, so a PM can mark each verdict right or wrong.

   The PM's verdicts give the accuracy number. That number, together with the
   Rupiah figure for work done outside the SOW, is the go/no-go evidence.

**The pilot data (details are confidential).**
- The contract, the answer key and the client name live in
  `apps/orchestrator/data/pilot/` (gitignored, see `NOTES.md` there). The
  repo is public; nothing from the contract is committed.
- **Thin baseline.** The pilot contract lists six modules with one-line
  features and no detailed specification, so the baseline is coarse.
  "Needs clarification" has to be a real outcome, not a failure.
- **Warranty bug fixes are in scope.** The contract makes fixing bugs and
  errors during the warranty a vendor obligation. Its additional terms say
  that scope changes are CRs, billed at a price agreed in writing.
- **The contract is a signed scan with an OCR text layer that has errors.**
  For example it reads "lntegrasi" for "Integrasi". Extraction must cope
  with that noise.
- **Answer key.** The PM already decided five real warranty requests: three
  CRs, two of which were done free as goodwill, and one grey item. A goodwill
  item still counts as a CR, because the work was out of scope; its value is
  recorded even when it is waived.

**The sample is too small, and one-sided.** The five real items are all CRs
or grey, so a check that labels everything "CR candidate" would score 5 out
of 5. The dataset therefore adds 15 synthetic warranty requests, written and
labelled by a delivery-expert reviewer at the user's request. About half of
them are In baseline.

**Effort units.**
- CR effort is in person-days.
- Person-days are converted to Rupiah with a **rate card**: a daily rate per
  role, set per project, in IDR.
- Story points stay as they are for sprint planning; CRs don't use them.

**After the POC.** These parts of the live flow wait for a positive backtest:
- the webhook trigger;
- writing the Scope label to Taiga;
- the sprint gate;
- the "Kemudi AI" service account.

A flow for linking existing tickets to baseline items goes into the backlog
for the next version.

## Goals

1. **SOW to draft backlog (BR-1.1).** A PM uploads an SOW, BRD or proposal
   (PDF or DOCX). AI drafts epics, user stories, acceptance criteria and a
   first estimate in person-days. Every item cites the SOW section it came
   from. The PM edits the draft before approving it.
2. **Locked, versioned baseline (BR-1.2).** The approved draft becomes
   baseline v1. Its items are kept as a separate reference list in the
   orchestrator and are not created as Taiga stories.
   The baseline changes only when a CR is approved, which creates a new
   version. Anyone can see the version history.
3. **Ticket classification (BR-1.3).** Every new story or issue gets one of
   three labels:
   - **In baseline**: the work is covered by the contract.
   - **CR candidate**: the work is outside the contract.
   - **Needs clarification**: the work can't be judged against the SOW yet.

   Each label comes with a reason and the SOW clause it relies on. The PM can
   change the label, and every decision is recorded. Tickets marked "Needs
   clarification" go back to the PM before they are classified again.
4. **CR draft and flow (BR-1.4, BR-1.5).** A CR candidate produces a draft CR
   with a description, an effort estimate and the schedule impact. The CR
   moves through Draft, Submitted, Approved or Rejected. The PM can export it
   as a document to send to the client. A story with a CR that isn't approved
   can't go into a sprint; projects can turn this rule off. Approving a CR
   adds its items to a new baseline version.

## Non-goals (this slice)

- Weekly status report (BR-1.6). It comes next, on top of this data.
- Client portal (BR-1.7) and the multi-client portfolio (BR-1.8). Both are V2.
- Awak writing code (BR-2.3 and on).
- Sending CRs to the client from inside Kemudi. Export is enough for MVP.
- Invoicing or accounting for approved CRs (out of scope in the BRD).
- OCR for scanned PDFs. Text-based PDF and DOCX only.

## Anti-goals

- **AI deciding.** AI only proposes. Labels and CR drafts are suggestions
  until a PM acts, and the UI must make that obvious (BRD section 11: clients
  see AI as a gimmick when it pretends to be sure).
- **Noise.** If the check flags most tickets, PMs will stop reading it, and
  the differentiator fails. Wording and layout should make a wrong label
  cheap to dismiss.
- **Forking deeper into Taiga.** Changes to `kemudi-back` must stay minimal
  and isolated (NFR-10, ADR 0001).

## Constraints (decided)

- **AI runtime: Hermes (`services/awak`), not Nexus AI.** The user decided
  this on 2026-11-11.
  - All model calls go through Hermes' OpenAI-compatible API server (port 8642).
  - The dev provider is `https://ai.sumopod.com/v1` with the default model
    `deepseek-flash`.
  - The settings are `KEMUDI_AI_BASE_URL`, `KEMUDI_AI_API_KEY` and
    `KEMUDI_AI_MODEL` in `infra/.env`. The key is never committed.
  - Models change through configuration, never through code.
- **Self-hostable.** Nothing in this slice may need a SaaS other than the
  configured model endpoint (BR-2.1).
- **Bilingual.**
  - Every new screen ships in Indonesian and English (`docs/i18n.md`). The
    glossary already says to keep "Change Request (CR)" and "SOW" in English.
  - AI-written text (reasons, CR drafts) is in the reader's language (BR-3.5).
    The project's working language decides what gets stored.
- **Auditability (NFR-4, BR-2.7).**
  - Every AI call is recorded with its prompt, model, tokens and estimated
    cost.
  - Every PM decision (approve baseline, change a label, move a CR) is
    recorded too.
  - The records are append-only; normal users can't edit them.
- **Licensing.** Code written for Kemudi (`apps/`) is AGPL-3.0-or-later.
  Changes in `services/kemudi-back` stay MPL-2.0 and are listed in
  `docs/third-party/kemudi-back-changes.md`.

## Shape of the system (my calls, open to the builder where marked)

```
apps/web ──(Taiga JWT)──► apps/orchestrator ──► Hermes API server ──► model endpoint
   │                           │   ▲
   │                           │   └── Taiga webhooks (new story / issue)
   └──► kemudi-back (Taiga API) ◄─┘   (creates epics/stories, sets the scope label)
```

- **`apps/orchestrator`: a new Python service.**
  - It owns the contract data: SOW documents and their extracted sections,
    baseline versions and items, ticket classifications, CRs, AI call records
    and the decision log.
  - The data lives in its own Postgres database on `kemudi-db`, not in
    Taiga's tables.
  - It authenticates requests by checking the caller's Taiga token against
    `kemudi-back`. Only project admins and members with a PM role can approve
    a baseline or move a CR.

    *(My call.)* "PM" here means a project admin. A finer role can come later.
- **Mirror to Taiga (after the POC).**
  - Baseline items stay in the orchestrator only. They are never copied into
    Taiga as stories.
  - Each ticket's scope label is written to a project custom attribute called
    "Scope". Its values are In baseline, CR candidate, Needs clarification and
    Pending CR.
  - Writing it there means the label shows in the existing item sheet and in
    filters, with no Taiga change.
- **Trigger.** A Taiga webhook, set up per project when the baseline is
  approved, tells the orchestrator about new stories and issues. Edits to the
  subject or description of an unclassified ticket trigger the check again.
- **Sprint gate (BR-1.5).** This needs a small isolated package in
  `kemudi-back`, in the same pattern as `sprint_access`. It rejects putting a
  story into a sprint while its Scope is "Pending CR". Each project can turn
  the gate off. This is the only Taiga change in the slice.
- **Hermes use.** Hermes gets a dedicated "kemudi" profile with every tool
  turned off: no terminal, no web, no file tools. This follows the BRD risk
  about Hermes tools reaching outside services. The orchestrator asks for
  structured JSON and validates it, and retries once on invalid output.
- **Documents.** The orchestrator extracts text from PDF and DOCX, keeps the
  heading numbering ("3.2 Modul laporan") as clause references, and stores
  the original file.
- **Long work.** Breaking an SOW into a backlog can take minutes. It runs as
  a background job, and the web UI shows its progress. A failed job keeps its
  input and can be retried.

## Screens in `apps/web` (new)

1. **Contract tab in a project.** It has three sections:
   - **SOW files:** upload, extraction status, and the extracted sections.
   - **Draft backlog review:** the draft items sit next to the SOW clause each
     one came from. The PM can edit, merge, delete or add items, then approve.
   - **Baseline:** the current version and the version history, with what
     changed in each version and which CR caused it.
2. **Scope label on tickets.**
   - Story rows, cards and the item sheet show the Scope label.
   - The item sheet also shows the reason and the SOW clause, with three
     actions: accept, change, or make a CR.
   - A filter for "CR candidate" and "Needs clarification" makes the review
     queue.
3. **Change Requests list and detail.**
   - The list can be filtered by status.
   - The detail page shows the draft text, effort, schedule impact, the
     linked tickets, the status flow and an export.

The visual direction follows `DESIGN.md` ("The Helm"). Scope labels follow its
rule that colour carries meaning only. Exact visuals are left to the builder,
within that system.

## Calls made after the builder check (author's calls, open to override)

- **Scope lifecycle.**
  - A new ticket is classified as In baseline, CR candidate or Needs
    clarification.
  - When a CR is drafted for a ticket, its Scope becomes Pending CR.
  - When that CR is approved, the ticket becomes In baseline and joins the
    next baseline version.
  - When the CR is rejected, the ticket becomes Rejected CR and stays out of
    sprints until a PM closes it or reclassifies it.
- **What the sprint gate blocks.**
  - The gate blocks every value except In baseline. That means CR candidate,
    Needs clarification, Pending CR and Rejected CR are all blocked; the BRD
    rule is "CR tickets that aren't approved can't enter a sprint".
  - The gate covers both stories and issues.
  - Tickets created before the baseline was approved, and projects that turned
    the gate off, are not blocked.
- **Tampering.**
  - The orchestrator is the record. The gate stays a single read of the Scope
    attribute, so `kemudi-back` gets no other change.
  - If someone edits Scope by hand in Taiga, the orchestrator notices through
    the webhook. It puts the value back, logs the attempt, and tells the PM.
  - If someone edits or deletes a baseline story in Taiga, that shows up as
    drift on the Baseline screen. Drift is reported, not silently fixed.
- **Language.**
  - Each project gets a working language on the Contract tab, Indonesian by
    default.
  - AI-written text is stored and shown in that language, and the CR export
    uses it too.
  - Text is not translated each time someone reads it.
- **Identity.**
  - An admin sets up a service account, "Kemudi AI", and adds it to the
    project when the contract is set up.
  - Automatic work (classification, mirroring) is written as that account.
    Anything a PM does is written with the PM's own token, so Taiga history
    shows the real person.
- **SOW addenda.** A later addendum or amendment changes the contract. It is
  uploaded on a CR as the CR's source document, never straight onto the
  baseline. Draft items can cite clauses from more than one document.

## Left to the builder

- The orchestrator framework (FastAPI or similar), the job runner, and the
  migrations tool.
- The prompt design and the JSON schemas for extraction, classification and
  the CR draft.
- The export format for a CR. DOCX or PDF, whichever is simpler to make well.
- How the baseline diff is shown.
- The cost estimate per call. Use the provider's token prices from config;
  the number is approximate.

## Measuring it (for the kill test)

Per project, the orchestrator must be able to answer these questions:

- How many tickets were classified, and with which label?
- How many labels did the PM override?
- How many CRs were drafted, how many submitted and how many approved, and
  the total effort of the approved ones?

These numbers feed G1 ("% of out-of-SOW requests logged as a CR before
work"), and they are the evidence for the go/no-go decision.
