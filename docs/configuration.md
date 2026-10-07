# Configuration and data handling

The web app runs locally and binds to `127.0.0.1`. Hosted means the language model is
remote; it does not mean this application is a public hosted service.

## Server options

| Option | Meaning |
| --- | --- |
| `--provider scripted` | Unpaid deterministic provider (default) |
| `--provider scripted-approval` | Unpaid provider with the approval/restart fixture |
| `--provider scripted-traces` | Unpaid provider that requests traces where available |
| `--provider anthropic` | Real model; requires your own key and positive spending ceiling |
| `--approved-budget-usd` | Explicit ceiling for the hosted ledger; no paid default |
| `--archive` | Local jobs, checkpoints, reviews and result directory |
| `--ledger` | Persistent hosted reservations/spending file |
| `--captured` | Root of local captures; the API reads immediate `*/case.json` children |
| `--port` | Local HTTP port; default 18090 |

Set `ANTHROPIC_API_KEY` only in the local server environment. `.env.example` is a
placeholder reference, not an automatically loaded configuration file. A non-official
`ANTHROPIC_BASE_URL` is rejected. No browser request can enable paid mode or supply a key.

The pinned model is `claude-haiku-4-5-20251001`. Its base input/output price is $1/$5 per
million tokens according to [Anthropic's model documentation](https://platform.claude.com/docs/en/models/haiku-4-5/overview),
checked 7 October 2026. Availability in a particular user's account was not tested.
Recheck model pricing and the adapter's accounting before future paid use.

## What leaves the machine

Hosted requests send the system prompt, alert, selected public evidence, tool-result
metadata and output schema to Anthropic. Private evaluator labels and fault controls
are not part of the provider payload. Evidence can still contain sensitive text if you
put it into a capture; schema validation is not a universal redaction system.

The application archives requests, reports, evidence, usage and execution activity
locally. API keys are not deliberately included in these records. Keep archives,
captures, ledgers and databases out of Git. Trace export uses allowlisted span fields
and excludes SQL, exception details and arbitrary attributes.

## Spending and restart

Start with a small explicit ceiling. Each dispatch reserves a conservative amount
before sending; known usage reconciles the reservation. Unknown outcomes retain their
reservation. The local cap does not cover other applications on your Anthropic account.

Keep the same archive, provider, ledger path and ceiling when resuming. Missing or
inconsistent state fails closed. Do not edit the ledger or create new ledgers to bypass
a previous ceiling. A paused approval does not consume active execution time.

Use separate archives for scripted practice and hosted investigations. A hosted
run requires a real human decision when the approval panel appears. Do not aim browser
automation or tests at a hosted server: clicking Start there can spend money.

## Troubleshooting

- Missing key/zero ceiling: set your own key and choose a positive ceiling.
- Endpoint rejected: remove an unintended custom `ANTHROPIC_BASE_URL`; this adapter
  supports the official service only.
- Existing ledger has a different ceiling: restart with its original approved ceiling.
- Blank UI/404: build `ui/dist` and launch the server from the repository root.
- Port occupied: choose another `--port`; do not stop unrelated servers.
- Unknown call outcome: inspect saved activity and retained reservations; start a new
  investigation if needed. The uncertain call is not automatically retried.
- Provider failure: confirm your account/key/model access independently; the unpaid
  fallback remains available. A schema-valid report is not proof of factual correctness.
