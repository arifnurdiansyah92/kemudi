# Security

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| Earlier development builds | No |

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub security advisories](https://github.com/arifnurdiansyah92/kemudi/security/advisories/new)
rather than in a public issue. Include the affected version, the component and
the steps to reproduce. You will receive an acknowledgement within five working
days.

## Deployment model

Kemudi is self-hosted. The operator controls the server, the network, the
database and the choice of AI model. The production configuration
(`infra/docker-compose.yml`) is designed so that a default installation is safe:

- **Secrets are generated, never shipped.** `scripts/init-secrets.sh` generates
  every secret. Compose refuses to start when a required secret is empty, and
  the orchestrator refuses to start in production with an empty or placeholder
  secret key or proxy token.
- **Local binding by default.** The gateway binds to `127.0.0.1` unless the
  operator chooses otherwise, and is intended to sit behind a TLS reverse proxy
  (see [docs/install.md](docs/install.md)).
- **Reduced surface.** The Django admin is not exposed, the legacy Taiga
  front-end is not part of the production stack, and security headers are set
  at the gateway.
- **AI features are opt-in.** Contract intelligence runs only with the `ai`
  profile; Awak runs only with the `awak` profile.

## Data flow

What leaves the operator's network depends entirely on the configured model
endpoint (`KEMUDI_AI_BASE_URL`, and any per-project model connection):

| Feature | Data sent to the model endpoint |
|---|---|
| Contract baseline | The full text of the uploaded contract |
| Change request check and backtest | The request text and the approved baseline |
| Intake | The pasted text or uploaded document |
| Awak | Story text, the content of the client repository it works on, command output and diffs |

When a **locally hosted model** is configured (for example through Ollama),
none of this leaves the network. When a **cloud provider** is configured, the
data above is sent to that provider and is subject to its terms. Organisations
with data residency obligations should use a local model.

Outside the model endpoint, Kemudi makes outbound connections only for git
operations, package installation and image pulls performed by Awak, and for
email delivery.

## Data protection

- **Model call records.** By default only hashes, token counts, cost and model
  are stored for each model call (`KEMUDI_AI_LOG_PROMPTS=false`). Records are
  purged after `KEMUDI_AI_LOG_RETENTION_DAYS` (default 90).
- **Contract deletion.** A project administrator can delete a project's
  contract together with its baselines, backtests, change request checks and
  related model call records.
- **Encryption at rest.** Model API keys, SSH keys, project environment
  variables and deploy commands are encrypted with `KEMUDI_SECRET_KEY`. The
  database volumes themselves are not encrypted by Kemudi; use disk encryption
  on the host.
- **Audit trail.** Merges, deploys, merge and QA policy changes, model
  connection changes, secret and key changes, skill approvals, budget changes,
  change request checks and verdicts, and contract deletion are recorded in an
  append-only audit log, exportable as CSV by project administrators. Secret
  values are never written to it.

## Awak: risks and recommendations

Awak executes code from client repositories. Its sandbox reduces but does not
remove the associated risks.

| Risk | Mitigation in Kemudi | Recommendation |
|---|---|---|
| Untrusted code runs during installation, tests and QA | Code runs in a separate Docker-in-Docker daemon with user-namespace remapping; Awak runs with dropped capabilities and `no-new-privileges` | Run the `awak` profile on a dedicated host or virtual machine |
| The Docker-in-Docker daemon runs privileged | It has no TCP listener and only the sandbox service can reach its socket | Treat the Awak host as a separate trust zone |
| Branch code has outbound internet access | — | Restrict egress with host firewall rules |
| Projects share one workspace volume | Each story uses its own git worktree | Use separate installations for clients that must be isolated from each other |
| Repository content or skills can steer the agent (prompt injection) | Skills are scanned and require approval; secrets are redacted from prompts on a best-effort basis | Use the **Approve** merge policy for production projects |
| Unreviewed changes reach production | Merge policy defaults to **Approve**; **Auto** requires browser QA | Do not use **Auto** for regulated clients |
| Unexpected model cost | Per-project monthly token budget and per-story cap | Set a budget before enabling Awak |

## Hardening checklist

1. Generate secrets with `scripts/init-secrets.sh` and store `infra/.env`
   securely. Back up `KEMUDI_SECRET_KEY`: without it, encrypted values cannot
   be recovered.
2. Terminate TLS in front of the gateway and set `KEMUDI_SCHEME=https`.
3. Keep the gateway bound to `127.0.0.1` behind the reverse proxy, or restrict
   access with a firewall.
4. Use a locally hosted model if contracts or source code must stay on-premises.
5. Enable the `awak` profile only on a dedicated host, with egress restrictions
   and a token budget.
6. Schedule backups as described in [docs/backup.md](docs/backup.md) and test a
   restore.
7. Apply new releases as described in [docs/upgrade.md](docs/upgrade.md).
