# Kemudi v1.0: release decisions and market validation (2026-11-14)

This record explains what v1.0 is, what it deliberately is not, and the evidence
behind those choices. It combines a three-expert panel review and a simulated
buyer panel.

## 1. Definition of v1.0

**Kemudi v1.0 is a self-hosted "pilot edition": an IT vendor installs it on its
own server to run one live client contract.** It locks the contract as a
baseline, checks requests against it on demand with the clause cited, turns
client briefs into stories, and provides full agile project management. Awak,
the AI delivery agent, is included as an opt-in, experimental component.

v1.0 is not a general enterprise release. Client-facing capabilities (client
portal, status reports, portfolio view, SSO, WhatsApp intake) are v1.x and v2
work.

## 2. Expert panel

Three independent reviews were run on the codebase on 2026-11-14.

| Panel member | Verdict | Key findings |
|---|---|---|
| Delivery and product | Release as a pilot edition only | The headline promise needs an on-demand CR check with recorded PM verdicts; Rupiah estimates must be hidden by default because the backtest overestimated by 31%; Awak needs a usage meter and budget; positioning must say "checks any request" rather than "flags every request" until automatic checking is measured on real tickets. |
| Security and compliance | Seven blockers | Weak default secrets with no startup check; LLM proxy open when its token is empty; services exposed on all interfaces over HTTP; full contract text logged indefinitely; deploy commands stored in plaintext; no audit trail for merges, deploys and configuration changes; development-only artefacts in the stack. |
| QA and release engineering | Do not tag until the release path exists | No production compose file, no published images, no CI for the backend or a full-stack smoke test, weak health checks and startup ordering, no HTTPS guidance, no install, upgrade or backup documentation. |

### Decisions

| Decision | Outcome |
|---|---|
| Scope of v1.0 | Pilot edition for one vendor and one contract. |
| CR check | Required for v1.0, on demand per ticket, with PM verdicts and CSV export. Automatic checking moves to v1.1 once accuracy is measured on real tickets. |
| Price estimates | Hidden by default; effort shown in person-days, marked indicative; Rupiah enabled per project. |
| Weekly status report | Deferred to v1.1 (first item). |
| Awak | Shipped as an opt-in, experimental profile with Approve as the default merge policy, a per-project token budget and accurate cost accounting. |
| Security | All seven blockers fixed before tagging; residual risks documented in `SECURITY.md`. |
| Release path | Production compose, GHCR images built on tag, smoke test in CI, install, upgrade and backup guides. |
| Positioning | "Checks any request against your contract in seconds, with the clause cited." |

## 3. Market validation (simulated buyer panel)

Twenty simulated buyers were drawn from the target profile: owners and delivery
heads of Indonesian software houses and system integrators (10 to 200 staff).
They were shown a pitch at Rp 75 juta per year plus Rp 25 juta setup, with a
Rp 15 juta 60-day paid pilot. Simulated buyers surface objections well but
overstate conversion; the figures below are directional only and must be
confirmed with real prospects.

**Result: 3 of 20 would buy the pilot (15%). None committed to the full year.**

| Segment | Buy rate |
|---|---|
| Small software house (10–30 staff) | 0 of 8 |
| Mid-size vendor (30–100 staff) | 2 of 8 |
| Established system integrator (100–200 staff) | 1 of 4 |

Buyers who had recently lost money on scope creep were the most likely to buy
(2 of 3).

### Findings

1. **The need is real and specific.** Almost every buyer recognised the problem
   of a recent scope dispute with a client. The scope checker is the reason to
   buy; the AI coding agent is not.
2. **Awak is a barrier for compliance-led buyers.** Bank and government
   integrators asked for a pilot with the coding agent switched off so a
   security review can be completed quickly.
3. **Price is the leading objection (11 of 17 passes).** The proposed price is
   above the "would not buy" point for most small and mid-size vendors. The
   median "expensive but would still buy" point was around Rp 35 juta per year.
4. **Switching cost from Jira is the second objection.** Several buyers asked for
   the scope checker as an add-on alongside Jira.
5. **Proof before commitment.** The most persuasive offer named by buyers was a
   retrospective audit of a finished project showing change requests that were
   never billed, with a Rupiah figure larger than the licence fee.
6. **Vendor longevity.** Buyers asked for a reference customer, a security pack
   and a support guarantee or source-code escrow.

### Implications

| Area | Action | When |
|---|---|---|
| Product | Awak remains opt-in and off in the default installation, so the scope checker can be piloted on its own. | v1.0 |
| Product | Position the existing backtest as a **retrospective scope audit** of a completed project; this is the recommended pilot. | v1.0 (documentation), v1.1 (import of past requests from Jira or CSV) |
| Product | Scope checking for teams that stay on Jira (import or connector). | v1.x, to be validated with real prospects |
| Commercial | Re-test pricing with a tier for mid-size vendors and a lower entry point; consider a pilot fee credited only if the audit finds billable change worth more than the fee. | Before the first sale |
| Commercial | Prepare a security pack: `SECURITY.md`, data-flow statement, installation without the AI agent, and a support or escrow statement. | v1.0 (documentation) |
| Go-to-market | Target mid-size vendors and system integrators that have recently lost money to scope creep; deprioritise small software houses. | Now |

The panel inputs (customer profile and pitch) and full results are kept outside
the repository; the seed is 148713 for reproducibility.
