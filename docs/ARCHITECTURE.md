# Architecture

## The idea

Most "AI agent" demos trust the model's output. This project does the opposite: the model only *proposes*,
and a statistical benchmark harness *decides*. An LLM edit is kept only if it is provably correct and
measurably faster.

## Components

| Module | Role |
|---|---|
| `runner.py` | Runs a command N times (plus warmup), samples wall time, CPU time and peak RSS. |
| `stats.py` | Welch's t-test or bootstrap, plus Cohen's d. A change is a regression/improvement only if `p < alpha` **and** `|d| >= min_effect`. |
| `agent.py` | The propose → verify → retry loop, the `Proposer` protocol, and three proposers (Claude, Ollama, scripted). |
| `evals.py` | Runs the agent over a folder of tasks; reports solve rate and mean attempts-to-solve. |
| `cli.py` | `bench run / compare / comment / optimize / eval`. |

## The agent loop (`agent.optimize`)

```
measure baseline (stdout + N timed runs)
repeat up to max_iterations:
    proposal = proposer.propose(original_source, command, history_of_rejections)
    write proposal to target file
    gate 1 (correctness): exit code 0 and stdout byte-identical to baseline   -> else revert, record, retry
    gate 2 (speed):       stats say wall-time IMPROVEMENT, no metric REGRESSION -> else revert, record, retry
    both pass -> keep the file, stop
nothing passed -> original file restored
```

Design decisions:

- **Verifier is independent of the proposer.** The same `judge()` runs whether the proposer is Claude, a local
  Ollama model or a script. The model cannot talk its way past the gates.
- **Rejections carry numbers.** Each retry prompt lists every failed attempt with its Δ%, p-value and effect
  size, so the model learns from measurements rather than guessing.
- **Always reversible.** Rejection, crash, exception and Ctrl-C all restore the original file (`try/except BaseException`).
- **Pluggable proposer.** One method (`propose`). Tests and CI use a scripted proposer, so the whole loop is
  verified offline and deterministically; live models are swapped in with a flag.
- **The agent is itself evaluated.** `bench eval` turns "it seems to work" into two numbers, and
  `--min-solve-rate` lets CI fail if the agent or harness regresses.

## Known limitations (deliberate scope cuts)

- **Correctness oracle is stdout equality.** It does not run a test suite, so a candidate could match output on
  the benchmarked input while being wrong elsewhere. A pluggable `--test-cmd` gate is the natural next step.
- **Timing noise.** Baseline and candidate are measured sequentially, not interleaved; a busy machine can cause
  false rejections (the cost of noise is a missed win, not a bad change landing). Mitigate with more `--runs`.
- **Executes model-written code without a sandbox.** Run it on a scratch copy; containerising is future work.
- **Single file, single objective.** Optimises one file for wall time; no multi-file edits or profiling tools yet.
- **CPU time is unreliable on Windows** for short-lived processes (documented in the README).
- **Scripted eval validates the harness, not the model.** Only the Claude/Ollama eval measures the agent.
