# CR check backtest: pilot project (2026-11-11)

**Result:** the CR check agreed with the PM on 19 of 20 warranty-period
requests. That includes all 5 real requests the PM had already decided. It
caught every Change Request and flagged none of the in-scope requests as a
CR. The effort and price estimates are not reliable yet.

This file holds aggregate numbers only. The client, the contract and the
dataset are confidential and live in `apps/orchestrator/data/` (gitignored).

## Setup

- **Contract.** A signed, scanned SPK (4 pages; the OCR text layer has
  errors). It covers six priced modules, warranty bug fixes as a vendor
  obligation, and a clause making scope changes billable CRs.
- **Baseline.** Drafted by the AI in one call (about 10 s), then approved
  without edits. It has 36 items:
  - 6 modules, with their contract prices read correctly;
  - 16 features;
  - 6 obligations;
  - 8 terms.
- **Dataset.** There are 20 requests in total.
  - 5 are real: the PM's own decisions, used as the answer key.
  - 15 are synthetic, written and labelled by a delivery-expert reviewer
    because the real history was never tracked. Some of these are decoys:
    in-scope work worded like a new feature, and CRs worded like bugs.
  - Rate card: Rp1.5 jt per day for PM and backend, Rp1.25 jt for frontend,
    Rp1 jt for QA.
- **Runtime.** `deepseek-flash` through Hermes, with every tool off. 21
  calls, about 3 s each.

## Numbers

| Measure | Result |
| --- | --- |
| Agreement with the PM's label | 19 / 20 (95%) |
| Real requests agreeing | 5 / 5 |
| CRs caught (labelled CR or needs clarification) | 8 / 8 (100%) |
| In-scope requests wrongly flagged as CR | 0 / 8 (0%) |
| The one miss | A grey item (export to Excel) labelled CR instead of needs clarification |
| Out-of-scope value, AI estimate vs PM | Rp113.4 jt vs Rp86.8 jt (+31%) |
| Real items only, AI estimate vs PM price | Rp37.1 jt vs Rp24.5 jt (+52%) |

Expected labels are in the rows and suggested labels in the columns:

| Expected | In baseline | CR candidate | Needs clarification |
| --- | --- | --- | --- |
| In baseline (8) | 8 | 0 | 0 |
| CR candidate (8) | 0 | 8 | 0 |
| Needs clarification (4) | 0 | 1 | 3 |

## What this does and doesn't show

- **Classification is strong enough for a pilot.** The check told warranty
  defects apart from new work, including the decoys, and it cited the right
  baseline items.
- **Price isn't reliable yet.**
  - Small items are badly overestimated: one Rp1.5 jt item came out at
    Rp12.25 jt.
  - Large items land closer to the PM's price.
  - Calibrating the estimates (past CRs as examples, or a role/size table)
    is the next fix before showing Rupiah figures to a client.
- **The test set is not independent.**
  - 15 of the 20 requests were written by an AI reviewer that had read the
    same contract.
  - The real sample is 5 items, all of them CRs or grey.
  - The kill test still needs live use: 2 to 3 sprints of real incoming
    requests on a running project, with the PM recording a verdict on each.
- **The PM review in the Contract tab is still open.** Each result can be
  marked right or wrong. Until it's done, the 95% is agreement with the
  answer key, not a PM-confirmed accuracy.

## How to reproduce

In the dev stack, open a project, then go to **Contract**:
1. Upload the contract.
2. Generate the draft baseline and approve it.
3. On **Backtest**, upload the dataset JSON.

The same steps are available from the CLI; see `apps/orchestrator/README.md`.
