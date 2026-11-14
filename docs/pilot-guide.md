# Running a Kemudi pilot

This guide takes a delivery team from a fresh installation to its first
evidence of value: change requests identified against a real contract. A
typical pilot covers one client contract over 60 days.

It assumes Kemudi is installed with the `ai` profile ([docs/install.md](install.md))
and that you are a project administrator.

## Recommended pilot: start with a retrospective scope audit

The most convincing first result is usually found in the past. Choose a recent
or completed fixed-price project where scope was contested, and measure what
the contract covered against what the client actually asked for.

1. **Create the project** in Kemudi, or import it from Jira, Trello, GitHub or
   Asana (*New project → Import*).
2. **Upload the contract.** On *Contract*, upload the signed SOW or SPK (PDF or
   DOCX) and choose its working language. Kemudi splits it into numbered
   sections.
3. **Review and approve the baseline.** On *Baseline*, generate the draft. Check
   every module, feature, obligation and term against the cited clause, edit
   where needed, and approve. The approved baseline becomes a locked version.
4. **Prepare the request history.** Collect the client requests received during
   the project (emails, meeting notes, WhatsApp messages, tickets) into a JSON
   dataset, recording for each one what the project manager decided at the
   time. The format is described in
   [apps/orchestrator/README.md](../apps/orchestrator/README.md#backtest-dataset).
5. **Run the backtest.** On *Backtest*, upload the dataset. Kemudi classifies
   each request against the baseline and compares the result with the original
   decision.
6. **Review the findings.** Requests classified as change request candidates
   that were delivered without a change order represent unbilled scope. Mark
   each result as right or wrong; this is the measure of how far the
   classification can be trusted on your contracts.

## Live use during delivery

Once the baseline is approved, apply it to new work as it arrives.

1. **Capture requests with Intake.** Paste a client email, meeting notes or a
   message, or upload a document. Kemudi drafts user stories with acceptance
   criteria; review them before they are created in the backlog.
2. **Check a ticket against the contract.** On any story or issue, open the
   item and choose *Check against contract*. The result shows the
   classification (in baseline, change request candidate, or requires
   clarification), the reasoning and the cited clauses.
3. **Record the decision.** Choose *Agree* or *Disagree*, with a corrected label
   and a note where needed. These verdicts are the evidence of accuracy on your
   own work.
4. **Export for the client conversation.** On *Contract → Checks*, export all
   checks and verdicts as CSV to support a change request letter or addendum.

### About effort and price estimates

Effort is shown in person-days and is **indicative**. Rupiah prices are hidden
by default because early measurements showed the estimates can be materially
too high, particularly for small requests. Enable prices on the *Contract* tab
only after the team has compared several estimates with its own judgement, and
never send an estimate to a client without review.

## Measuring the pilot

At the end of the pilot, the following figures summarise its value:

| Measure | Source |
|---|---|
| Agreement between Kemudi and the project manager | Verdicts on *Contract → Checks* and the backtest |
| Change request candidates identified | *Contract → Checks* and the backtest |
| Value of change requests raised with the client as a result | The team's change request log |
| Time spent assessing requests, before and after | Project manager estimate |

## Optional: Awak

Awak, the AI delivery agent, is not required for a scope pilot and is off in a
default installation. Teams that want to evaluate it should first read the
Awak section of [SECURITY.md](../SECURITY.md), run it on a dedicated host, keep
the **Approve** merge policy, and set a monthly token budget in
*Project settings → Agent*.
