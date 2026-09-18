# Working-context results — 2026-09-19

Three concrete freshness/delivery bugs were fixed: extensionless or mixed file
references bypassing freshness checks, normalized references missing active-file
retrieval, and failed hooks suppressing the next successful context delivery.
The experiments below characterize the implementation. They do not establish
general coding accuracy, reliability, cost savings, or superiority to Claude Code.

## Component results

[Raw event rows and implementation hashes](component.json) cover 351 events:
three arms × three corpus sizes × three seeds × thirteen events. Adaptive mode
passed **117/117 claim-eligibility checks**, with zero delivery, constraint, or
budget failures. These are nine correlated synthetic streams, not 117 coding tasks.
Legacy recall passed 99/117 and included the old claim in eighteen source-edit or
deletion events. It correctly excluded quarantined memory.

| Stored memories | Adaptive median | Adaptive p95 | Adaptive warm p95 |
|---:|---:|---:|---:|
| 100 | 1.891 ms | 19.210 ms | 2.326 ms |
| 1,000 | 2.087 ms | 19.198 ms | 2.832 ms |
| 10,000 | 2.481 ms | 20.195 ms | 3.146 ms |

Times include compiler SQLite/source/Git work, but exclude setup and native hook
process startup. Warm measurements exclude each stream's initial packet. This was
one macOS arm64 host during local validation; noise memories are unrelated to the
query. This is a modest retrieval workload, not semantic retrieval evidence.
[Host and dependency versions](environment.json) were captured from the unchanged
benchmark environment after the runs.

| Arm | Total emitted characters | Stale/deleted claim inclusions |
|---|---:|---:|
| Legacy recall, full Markdown, same pinned constraints | 18,189 | 18 |
| Adaptive | 49,266 | 0 |
| Adaptive, forced delivery on every event | 77,571 | 0 |

Deduplication reduced emitted characters **36.49% against forced adaptive
delivery**. Adaptive still emitted 2.71× as many characters as legacy recall and
was slower: legacy p95 at 10,000 memories was 0.817 ms. The extra packet carries
session state, authority/freshness information, and withdrawals. No LLM token or
monetary savings can be inferred from these character counts. Previously delivered
text cannot be erased from an agent's conversation.

## Live coding pilot

[All six results, prompts, final sources, patches, usage, and trace hashes](live.json).
Codex CLI used `gpt-6-astra`, medium effort, one attempt per arm/task, with a
180-second timeout. Both arms had identical current contracts, historical notes,
initial source, and ONMC state. Adaptive additionally received the compiled packet.
Arm order alternated. No retries were selected for favorable results.

| Task | Baseline external tests | Adaptive external tests | Baseline time | Adaptive time |
|---|---:|---:|---:|---:|
| Cache expiration | 6/6 | 6/6 | 61.591 s | 62.234 s |
| Atomic replay-safe ledger | 6/6 | 6/6 | 69.777 s | 71.187 s |
| Half-open interval normalization | 6/6 | 6/6 | 64.703 s | 55.149 s |
| Total | 18/18 | 18/18 | 196.071 s | 188.570 s |

**Task success: 3/3 versus 3/3, a tie.** No infrastructure failures or timeouts.
Three small synthetic tasks saturate both arms. The observed timing difference
is descriptive and is not evidence of a speed improvement.

| Provider-reported usage, summed over three runs | Baseline | Adaptive |
|---|---:|---:|
| Input tokens | 358,100 | 350,971 |
| Cached input tokens, as reported | 284,672 | 282,624 |
| Output tokens | 5,047 | 4,654 |

Usage is copied from each CLI `turn.completed` event. Tool-use model requests and host
instructions contribute to these totals. Cached usage is shown separately; no
billing calculation is attempted. Dollar costs are unknown.

All six traces read shared global agent guidance; optional skill reads varied.
`--ignore-user-config` does not isolate host instruction files. This affects
reproducibility and can confound usage/latency. Audit found no recorded access to
other trials or grading fixtures. Raw provider logs contain host guidance and remain
local; their SHA-256 hashes and command lists with host paths replaced are published.
These are ordinary agent trials, not a sandbox against adversarial test exfiltration.

## Grading and provenance

External tests were materialized after each agent exited. The grader copies only
`solution.py` into a fresh directory, preloads standard-library test dependencies,
and requires six tests with no skips. Candidate-written tests do not decide success.
Original contract/history/instruction hashes must remain intact. Source snapshots
and patches are captured independently of whether an agent stages or commits edits.
Every attempted provider call remains in the denominator, including exceptions.

Reference implementations pass all eighteen distinct checks; untouched stubs fail.
Negative controls detect missing expired-entry cleanup, malformed ledger identities,
incorrect adjacency merging, a shadowed zero-test grader, and a context compiler
that emits nothing. These checks validate the benchmark's detection boundaries;
they do not prove the grading contracts exhaustive.

Runs started from Git revision `64a4485c318c3d34d57496750ab4e9716fdc1b52` plus the
reviewed working changes. Per-file hashes identify the exact benchmark and context
implementation bytes and match the files shipped with this report. Logical corpus
hashes exclude setup timestamps. Reproduction may change timing and model outputs.

## Frozen retrieval benchmark

[Unmodified benchmark output](retrieval.json): BM25 Recall@5 **0.950**, nDCG@10
**0.8574**, across forty frozen code queries. Hybrid: 0.875 / 0.8082. Dense-only
hash-ngram: 0.750 / 0.6683. Graph ranking remains explicitly skipped. This confirms
BM25's lead on this small corpus; it does not measure adaptive working context or
general agent task success.

See the [protocol and run commands](../../working-context.md). No SWE-bench run or
Claude live run was performed. Claude authentication was unavailable; Codex was
explicitly selected for this pilot.
