# Changelog

All notable changes to Kemudi are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-14

The first release of Kemudi: a self-hosted pilot edition for IT vendors running
a client contract. See [docs/install.md](docs/install.md) to install it and
[docs/pilot-guide.md](docs/pilot-guide.md) to run a pilot.

### Contract intelligence

- Contract upload (PDF or DOCX) and segmentation into numbered sections.
- Baseline drafting of modules, features, obligations and terms, each traceable
  to its clause and contract value, with review and versioned approval.
- On-demand change request check for any story or issue, classifying it as in
  baseline, change request candidate or requiring clarification, with the
  reasoning and cited clauses.
- Project manager verdicts on each check, and CSV export of all checks.
- Effort estimates in person-days, marked as indicative; Rupiah prices hidden by
  default and enabled per project.
- Backtest of historical requests against the baseline, for retrospective scope
  audits and accuracy measurement.
- Intake: conversion of briefs, notes, emails and documents into draft user
  stories with acceptance criteria, in English or Bahasa Indonesia.

### Project management

- A new web interface at full parity with Taiga: epics, backlog and sprint
  planning, taskboard with burndown, kanban, issues, wiki, timeline, saved
  filters, roles and permissions, webhooks, Git integrations, and importers for
  Jira, Trello, GitHub and Asana.
- Sprint-level access control per role.
- English and Bahasa Indonesia interface with localised dates, currency and time
  zones.

### Awak (experimental)

- Story-to-branch implementation with install, lint, type-check and test gates,
  browser verification of acceptance criteria with screenshot evidence, and up
  to three attempts.
- Merge policies (Manual, Approve, Auto) and QA levels (off, gates only,
  browser), with Approve as the default.
- Project workspace, runbook, encrypted environment vault and the Setup
  Assistant.
- Skills library and marketplace with security scanning, licence checks,
  pinned versions and update approval.
- Bring-your-own model connection for any OpenAI-compatible endpoint, including
  local models.
- Per-call token and cost accounting with a per-model price table, a
  per-project monthly token budget and an optional per-story cap.

### Security

- Production startup checks for empty or placeholder secrets.
- The model proxy requires its token, compared in constant time.
- Model call records keep hashes rather than prompt text by default, with a
  configurable retention period.
- Contract deletion, including baselines, backtests, checks and related model
  call records.
- Encryption at rest for deploy commands, in addition to keys and environment
  variables.
- Append-only audit trail for merges, deploys, policy and configuration changes,
  secrets, skills, budgets and change request decisions, with CSV export.
- Security policy, data-flow statement and hardening checklist in
  [SECURITY.md](SECURITY.md).

### Operations

- Production Docker Compose configuration with pinned images, health checks,
  health-ordered start-up, required-secret validation and local binding by
  default; AI features and Awak as opt-in profiles.
- Production gateway configuration with security headers and optional TLS.
- Secret generation script.
- Container images published to GitHub Container Registry for each release.
- Full-stack smoke test in continuous integration.
- Installation, upgrade and backup guides.

### Known limitations

- Change request checks run on demand; automatic checking of every new ticket
  is planned for 1.1.
- Price estimates are not yet calibrated and are hidden by default.
- Weekly status reports, a client portal, a portfolio view, WhatsApp intake and
  single sign-on are not included.
- Awak is experimental, runs a privileged Docker-in-Docker daemon, and should be
  deployed on a dedicated host.
- Container images are built for amd64 only.
- Bahasa Indonesia interface text is awaiting native-speaker review.

[1.0.0]: https://github.com/arifnurdiansyah92/kemudi/releases/tag/v1.0.0
