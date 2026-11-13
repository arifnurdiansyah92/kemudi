# Awak project setup: repos, agents, machines, merge policy, intake UI

Status: iteration 2 design, 2026-11-14. It builds on iteration 1
(`2026-11-13-awak-dev-loop-design.md`, results in
`docs/poc/2026-11-awak-loop-iteration-1.md`). The user opted out of a Q&A
round; anything not quoted from them is the builder's call and is marked
**(call)**.

## Intent

In iteration 1, the Awak loop is hard-wired to one project (Kemudi's own
monorepo). Its settings live in environment variables, and intake has no UI.
The user wants every project to be set up once, and changeable later, from
inside Kemudi:

> "repo git (termasuk jika bukan monorepo), agent system prompt … agent front
> end dev … kasih system prompt seperti style coding (default dari kita, tapi
> human punya control) … server kuat untuk running project … human bisa kasih
> custom vps / ssh"

> "Auto-merge ini bisa fully auto bahkan sampai prod juga (termasuk merge ke
> main) … kasih opsi aja human nya"

> "soal setting per project kita perlu siapkan tempat untuk update settingan
> itu, mungkin saja di awal dia ga mau pake agent terus nanti pake agent atau
> kebalikan nya"

> "yg intake (yg dari cerita jadi story / task) itu perlu dibuatkan ui aja"

## Goals

1. **Agent settings page per project** (Project settings → Agent). The admin
   can turn Awak on or off at any time, and the worker reads this setting
   instead of an environment variable.
2. **Repositories.** A project has one or more repos. Each repo has a name,
   a role (`web`, `api`, `mobile`, `other`), a git URL, a default branch,
   and the commands for install, check, build and run (detected, then
   editable).
   - Access is through a **per-repo SSH deploy key that Kemudi generates**.
     The admin pastes the public key into GitHub or GitLab with write access.
   - The Kemudi repo itself keeps working through the local `.git` path.
3. **Agent roles with layered prompts.** The final system prompt is three
   layers:
   - **Kemudi rules**, fixed and not editable: the safety and git rules from
     iteration 1.
   - **Role template**, a Kemudi default: Frontend dev, Backend dev, QA.
   - **Project overlay**, written by the human: coding style, conventions, do
     and don't.

   Each role also has a model, a repo scope (which repos and paths it may
   touch), and enabled on/off. A story goes to a role by its area tag. Every
   job records the prompt version it used.
4. **Merge policy per project**, chosen by the human:
   - `manual`: Done plus `awaiting-merge`; a human merges outside Kemudi.
     This is the iteration 1 behaviour.
   - `approve`: a **Merge** button on the story card. A human clicks it, and
     Kemudi merges the branch into the default branch and pushes.
   - `auto`: when QA passes, Kemudi merges into the default branch and
     pushes right away. This is fully automatic "sampai prod" for small or
     test projects.

   Optionally, a **post-merge deploy command** runs on the execution machine
   after the merge (for example `docker compose up -d --build` or a deploy
   script). Its output is posted to the card.
5. **Execution machine per project:**
   - `local`: Kemudi's own Docker host, as today.
   - `ssh`: a custom VPS (host, port, user, Kemudi-generated SSH key).

   A **preflight check** shows CPU, RAM, disk and whether Docker is present
   against the recommended minimum: **4 vCPU, 8 GB RAM, 40 GB free disk per
   concurrent job**, measured in iteration 1. It also shows how many job
   slots the machine fits.
6. **Intake UI.** An "Intake" page in the project. The PM pastes a story or
   requirement text, or uploads a PDF/DOCX. They see the drafted stories
   (subject, description, criteria, area, and whether each will go straight
   to Ready or wait in New), edit or drop some, then click **Create stories**.
   This replaces the direct-create behaviour for UI use; the CLI keeps
   direct create.
7. **Jobs panel.** The Agent settings page lists the recent jobs: story,
   state, phase, attempts, cost and branch.

## Non-goals (this iteration)

- **Remote execution of agent jobs on an SSH VPS.** This iteration stores the
  SSH target, generates its key and runs the preflight over SSH (CPU, RAM,
  disk, Docker). Actually running Awak and the runner there is the next
  iteration. **(call)** That is a container orchestration job on a remote
  host, with its own security review. The UI says so plainly: the machine
  can be checked, but jobs run on `local` until remote execution ships.
- Per-story preview environments (next iteration after remote execution).
- Opening PRs through provider APIs. Merging is plain git: merge, then push
  with the deploy key, so it works on any host. **(call)**
- Parallel jobs.

## Anti-goals

- Private keys or deploy secrets shown in the UI after creation, put in a
  prompt, or written into a comment.
- A human editing away the Kemudi safety rules through the prompt overlay.
- `auto` merge pushing something that did not pass gates and QA on the
  commit being merged.
- `auto` merge being the default. **(call)** The default is `approve`.
- Writes to a Taiga that is not the local stack, for the dev loop (unchanged).

## Data and API (orchestrator)

**Storage.** New tables in the orchestrator's SQLite:
- `awak_projects` (slug, enabled, merge_mode, deploy_command, executor,
  ssh fields, updated_by/at);
- `awak_repos`;
- `awak_roles` (with `prompt_overlay` and `version`);
- `awak_keys` (private keys stored in the orchestrator volume, encrypted at
  rest with a key from the environment **(call)**).

Changes are recorded in `decisions`.

**Endpoints.** Under `/api/kemudi/projects/{slug}/agent/...`. Reads need
project membership; writes need project admin.
- `GET/PUT settings`
- `GET/POST/PUT/DELETE repos`, plus `POST repos/{id}/key` (generate, returns
  the public key only) and `POST repos/{id}/check` (can Kemudi clone and
  push)
- `GET/PUT roles`, plus `GET roles/{id}/prompt` (the rendered three layers,
  the fixed one read-only)
- `POST machine/check` (preflight)
- `GET jobs`
- `POST stories/{id}/merge` (approve mode)
- `POST intake/draft` (returns drafts, creates nothing) and
  `POST intake/create` (creates the stories the PM kept)

**Worker changes:**
- Read the enabled projects from the DB, still honouring
  `KEMUDI_AWAK_PROJECTS` as a bootstrap seed.
- Pick the repo and role by the story's area.
- Build the prompt from the three layers.
- After QA passes, apply the merge mode. For a merge, merge onto the latest
  default branch. If that merge is not a fast-forward of the QA'd commit,
  re-run the gates on the merged result before pushing.

## UI (apps/web)

Follow DESIGN.md and PRODUCT.md, and run the impeccable skill on the new
surfaces. These are Operate mode surfaces: precise, calm, consistent with
the existing settings pages. Use English UI copy with Indonesian
translations through i18next.

1. **Project settings → Agent:**
   - an on/off switch;
   - merge policy as three radio cards, each with an honest sentence about
     its risk;
   - the deploy command;
   - the machine, local or SSH, with a preflight result;
   - repos, as a list with an add form, the generated public key with copy,
     and a "Check access" result;
   - roles, as a list with an editor showing the fixed layer read-only above
     the editable overlay, a model picker and an enabled switch;
   - recent jobs.
2. **Project → Intake:** a page with a text area and a file drop, a "Draft
   stories" button, an editable draft list and "Create stories". Shown only
   when the agent is enabled? **(call)** No: intake is useful without Awak.
   Stories created while Awak is off simply wait.
3. **Story detail:** when the project's merge mode is `approve` and the story
   carries `awaiting-merge`, show a **Merge** button for admins, with the
   result shown inline.

## Left to the builder

Table and field names, the shape of the detection heuristics, encryption
details, component breakdown, test doubles.
