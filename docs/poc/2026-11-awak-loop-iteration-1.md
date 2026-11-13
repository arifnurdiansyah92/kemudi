# Awak dev loop: iteration 1 results (2026-11-14)

**Result:** 5 of 5 small frontend stories went from a one-line request to
Done. Each was on its first counted attempt, with all four gates green and a
Playwright QA pass backed by a screenshot per acceptance criterion. The bar
in the [design](../superpowers/specs/2026-11-13-awak-dev-loop-design.md) was
3 of 5.

## Setup

- **Stack and model.** The local dev stack with `--profile awak`. Awak and QA
  both ran on `deepseek-flash`.
- **Requests.** Written in Indonesian and turned into stories by intake (one
  LLM call for each request). All five landed in Ready with `agent-ready`.
- **Project.** The dogfood project is `kemudi`. QA ran as `awak-qa` against
  the `awak-qa-sandbox` project.

## Stories

| US | Story | Files changed | Gates | QA | Time |
| --- | --- | --- | --- | --- | --- |
| 1 | "Projects (N)" in the Projects heading | 3 | 4/4 | 3/3 AC | ~5 min after fixes |
| 2 | "Private" label on private project cards | 4 | 4/4 | 2/2 AC | 8 min |
| 3 | "Back to projects" button on the 404 page | 4 | 4/4 | 2/2 AC | 4 min |
| 4 | @username under the full name in Your settings | 2 | 4/4 | 1/1 AC | 5 min |
| 5 | Project count badge on the sidebar's Projects item | 3 | 4/4 | 2/2 AC | 8 min |

"Time" runs from pickup to Done. Each story's branch `awak/us-<n>` is in the
local repo, unmerged. Done carries the tag `awaiting-merge`.

## What the first live run found (fixed)

1. The runner's `pnpm` was not on PATH.
2. Playwright's browser installer hangs on the image's Node 26, so the runner
   now downloads and unpacks the pinned Chromium builds itself.
3. `git fetch` from Awak's workspace was refused as "dubious ownership"
   because the workspace belongs to Awak's uid. `upload-pack` now gets
   `safe.directory`.
4. Every infra retry repeated the coding run. A retry after coding now
   resumes from collect, and unblocking an infra-blocked story resumes too.

The infra guard worked as designed throughout: three environment failures
blocked the card with `needs-human` and a comment naming the cause, and none
of them used up an attempt.

## Cost

These are the stories 2 to 5 (a clean run):

| Call | Calls | Prompt tokens | Completion tokens |
| --- | --- | --- | --- |
| `awak.code` | 4 | 4.25 M | 47 k |
| `awak.qa` | 4 | 4.44 M | 61 k |

That is about 2.2 M tokens per story, almost all of it prompt. Hermes resends
the whole conversation on every tool turn. Ways to bring this down, before any
use beyond dogfooding:

- Hermes context compression settings.
- Fewer exploratory reads, through a repo map in the prompt.
- Prompt caching on the provider.

## Not shown yet

- **Rework.** No story failed QA, so live rework is covered only by unit tests.
  A story that is harder, or deliberately ambiguous, would exercise it.
- **Backend stories.** By design, intake holds them in New.
- **Independence of QA.** QA specs are written by the same model family as the
  code. For example, US #2's QA mocked a public project to check the negative
  case. Done is not a review: a human still reads each branch before merging.
