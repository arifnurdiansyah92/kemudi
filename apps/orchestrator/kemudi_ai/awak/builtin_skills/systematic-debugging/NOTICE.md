# Notice

Kemudi vendors `skills/systematic-debugging` from obra/superpowers (MIT, see
`LICENSE`) at commit 22f0b463e7a5e579904dd6211a520321035526f7 (v7.0.2) and has modified one line of `SKILL.md`:
the multi-layer example checks whether `IDENTITY` is exported with
`sh -c '[ -n "${IDENTITY:-}" ]'` instead of the original environment-printing
command, because Kemudi's skill scan rejects commands that can print the
environment. No other
file was changed; `LICENSE` was added from the repository root.
