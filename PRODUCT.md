# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: IT vendors and system integrators delivering projects under contract** (Aegislabs is the reference case), running Kemudi inside their own or their client's infrastructure. Inside the vendor:

- Delivery teams (developers, PMs, BAs, QA) doing day-to-day sprint and kanban work. They think in English agile terms.
- Delivery leads and management watching every client project at once for schedule risk, scope drift and margin.

**Secondary: client stakeholders** (directors, project officers at banks, BUMN and government agencies) who follow progress through a read-only client portal and status reports, separate from the vendor's internal chatter. They are more comfortable in Indonesian.

## Product Purpose

Kemudi is the delivery control system for IT vendors working under contract. It makes the contract the measuring stick for the whole project, so the vendor catches scope drift as billable change, keeps the client informed without exposing internal work, and protects margin across a portfolio of clients.

Success: every out-of-scope request is caught and priced, the client sees trustworthy status without asking, and a lead can see which projects are red/amber/green and how their margin is doing on one screen.

## Positioning

> "Kemudi turns your contract into a backlog, flags every out-of-scope request as a billable change, and lets an AI crew ship the work, all inside your own infrastructure."

Kemudi does not compete on "AI on a kanban board". Jira and Linear already own that. Agents on a board are table stakes that make Kemudi credible, not different. The four differentiators:

1. **Built for vendors, not product teams.** It understands the contract: SOW → baseline backlog, CR Detector, client-facing layer, multi-client portfolio.
2. **Runs where the data must stay.** On-prem, with a swappable AI engine: Claude Code where the client allows cloud, Hermes with a local model where they don't. For banks, BUMN and government this alone decides the deal.
3. **Speaks the client's language and channel.** Bahasa Indonesia natural-language commands and reports. WhatsApp as an intake channel.
4. **Predictable cost.** A flat annual on-prem license plus implementation, with no AI usage meter. This fits how Indonesian enterprise procurement buys.

Where Kemudi deliberately does not try to win:

| Battle | Who wins | Kemudi's stance |
|---|---|---|
| UI speed and polish | Linear | Good enough, not a selling point |
| Integration ecosystem and marketplace | Jira | Essentials only: GitLab/GitHub, WhatsApp, SSO |
| Free self-hosted PM | Stock Taiga / Plane | Kemudi is the paid layer on that free core |

## Operating Context

- Project lifecycle starts from a signed SOW. The client watches progress, scope drifts mid-project, and the vendor's margin depends on catching that drift.
- Deployed self-hosted or on-prem in the vendor's or client's infrastructure, often in regulated environments (banks, BUMN, government).
- Clients send requests informally, often by WhatsApp message or voice note.
- Multi-region clients across WIB/WITA/WIT time zones.
- Sales demos: the live language switch (developer view in English, then the client portal in Indonesian on the same project data) is a core demo moment.

## Capabilities and Constraints

**Built today:**

- Backend: fork of taiga-back 6.10.2 and taiga-events (`services/`), Taiga REST API and websocket.
- `apps/web`: React 19, Vite, TanStack Router/Query, Tailwind 4, shadcn/ui. It covers taiga-front parity: epics, backlog, sprints and taskboard, kanban, issues, wiki, team, timeline, item sheet, filters and saved filters, project admin, importers, plus sprint access. It has no i18n yet; all strings are hard-coded English.

**Planned, not built** (never present these as shipping):

- SOW → baseline backlog, CR Detector (out-of-baseline tickets flagged as billable Change Requests with an effort estimate), auto-generated status reports, read-only client portal, multi-client portfolio with RAG status and margin health.
- Awak, the AI agent (fork of hermes-agent), the orchestrator and the code sandbox. Swappable engine: Claude Code or Hermes with a local model.
- WhatsApp intake. GitLab/GitHub and SSO integrations.

**Bilingual from day one (binding):**

- Bahasa Indonesia and English, switchable per user. Three layers of setting: per user, per workspace (default for new members), and per client portal (usually Indonesian, independent of the vendor team).
- An i18n framework in `apps/web` with no hard-coded UI strings, enforced by a CI check that fails on one. The existing strings must be migrated.
- Awak's output and reports follow the reader's locale: developers get English agent comments, the client's weekly report arrives in formal Indonesian.
- Locale formats, not just words: dates (11 Nov 2026), currency (Rp1.500.000), number separators (1.000,50), time zones (WIB/WITA/WIT).
- Layouts must absorb longer Indonesian strings in buttons and table headers without breaking.
- Emails and notifications come from kemudi-back. Its `id` locale exists, but its coverage must be verified separately.

**Terminology glossary** (enforced in UI, docs and Awak's prompts):

| Keep in English (industry jargon) | Translate (general UI and actions) | Never translate (brand) |
|---|---|---|
| Sprint, Backlog, Kanban | Save → Simpan, Cancel → Batal | Kemudi |
| Story Point, Epic | Assignee → Penanggung Jawab | Awak |
| Pull Request, Merge | Due date → Tenggat | Kemudi Radar |
| Change Request (CR) | Comment → Komentar | Kemudi Assist |
| QA, UAT | Settings → Pengaturan | |

## Brand Commitments

- Names: **Kemudi** (product), **Awak** (AI agent), **Kemudi Radar**, **Kemudi Assist**. These are never translated.
- Indonesian voice: address the user as "Anda", semi-formal. Enterprise-appropriate without sounding stiff.
- UI copy in Indonesian is reviewed by a native speaker. Do not ship machine translation.
- Open-source core under AGPL-3.0-or-later. Forks keep MPL-2.0 or MIT.
- Self-hosted privacy: nothing goes to third parties by default (for example, no Gravatar fallback).

## Evidence on Hand

- Working parity UI in `apps/web` and a seeded demo project (`kemudi-demo`) for screenshots and demos.
- Competitor facts as stated by the owner: Jira AI credits with overage at $0.01 per credit from 3 Dec 2026; Linear agents gated to the Business tier ($14/user/month); Linear's CEO says coding agents are installed in 75% of its enterprise workspaces.
- No customers, testimonials, case studies, benchmarks or published pricing exist yet. Do not fabricate them. Aegislabs is the reference vendor, not a published case study.

## Product Principles

1. **The contract is the source of truth.** Every screen that touches scope should help answer "is this in the baseline, and if not, what does it cost?"
2. **Two audiences, two layers.** Internal delivery work and client-facing views are separate by design. Nothing internal leaks to the client without intent.
3. **Built for Indonesian delivery, not translated for it.** Language, formats, channels and procurement fit are product features, not localisation chores.
4. **Data stays where the client needs it.** Every feature, AI included, must work fully on-prem, without a cloud dependency.
5. **Table stakes stay good enough.** Board UX, speed and integrations meet expectations. Effort goes to the differentiators.
