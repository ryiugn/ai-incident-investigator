# Evaluation methodology and private ground truth

The question is whether adaptive evidence collection provides more useful, supported
diagnoses than a fixed checklist at acceptable cost and latency. No winner is assumed.

The public release contains evaluation code, not the original benchmark corpus,
private answers, named reviews or historical output archives. Ordinary tests construct
synthetic fixtures and do not require private files. Those test judgments are not
actual human reviews or evidence of model performance.

## Generate a new local corpus

With the optional laboratory running, `python -m benchmark.dataset` generates twenty
controlled captures and forty variants across five fault families. It writes public
snapshots under `benchmark/public` and evaluator-only labels/splits under
`benchmark/private`. Both directories are ignored. Generation replaces local dataset
files; use a fresh checkout/directory and never regenerate a frozen evaluation corpus.

Related variants share a generation group and cannot cross development/held-out splits.
Machine-checked signatures do not establish human answerability or causal specificity.
Missing-evidence and adversarial variants exercise boundary behavior.

## Scripted comparison

```text
docker build -f Dockerfile.investigator -t ai-investigator-runtime:local .
python -m benchmark.evaluate --config benchmark/configs/development.json
```

The harness requires a Git commit and archives source/config/dependency/image identities.
Each scripted run gets one public case through stdin in a read-only network-disabled
container. Private labels, the Docker socket and fault controls are not mounted into
the investigator. Hosted experiments necessarily enable provider network access.
Generated results remain local under `benchmark/results`.

## Actual quality evaluation

Audit labels and supported diagnostic levels against exposed evidence using
`benchmark.label_review`. Its CLI can export packets and import completed attestations;
see `python -m benchmark.label_review --help`. Human reviews must remain human decisions.
Paid non-exploratory batches require audited labels and their matching frozen sources.
The limited exploratory path is development-only and explicitly not benchmark findings.

Freeze prompts/settings after development, obtain separate approval for spending,
and review reports before drawing held-out conclusions. The supplied held-out config
has three repeats; it is not authorization to make paid calls. Account credentials and
an explicit budget are required, and no such experiment was run for this public release.

All scheduled failures stay in denominators. Paired uncertainty uses capture groups,
not forty supposedly independent variants. Citation validity, valid JSON and completion
rate are software measures; semantic correctness and claim support need actual review.
Solo-author knowledge, short captures, synthetic faults and the small local system
limit external validity. Public run comparisons show compatible evidence and usage,
not private-label correctness or an automatic winner.
