# Performance Regression Benchmark Harness

A CLI tool that runs a program before and after a code change, captures timing and memory stats across N runs, applies a statistical significance test to separate real regressions from noise, and posts the result as a GitHub PR comment automatically.

```
bench run "python my_script.py" --label before --runs 20
# ... make your change ...
bench run "python my_script.py" --label after  --runs 20
bench compare before.json after.json
```

```
Comparison: before → after
┌───────────┬───────────┬──────────┬─────────┬─────────┬───────────┬─────────────┐
│ Metric    │ before    │ after    │ Δ%      │ p-value │ Cohen's d │ Verdict     │
├───────────┼───────────┼──────────┼─────────┼─────────┼───────────┼─────────────┤
│ Wall time │ 0.2163 s  │ 0.1092 s │ -49.52% │  0.0000 │    -7.264 │ IMPROVEMENT │
│ Peak RSS  │ 13.67 MB  │ 13.17 MB │  -3.65% │  0.0001 │    -3.975 │ IMPROVEMENT │
└───────────┴───────────┴──────────┴─────────┴─────────┴───────────┴─────────────┘
✓ IMPROVEMENT detected
```

---

## Features

- **Subprocess benchmarking** — benchmark any shell command, language-agnostic
- **Warmup runs** — throw away the first N runs to warm JIT/caches before measuring
- **Wall time + peak RSS** — collected per run; CPU time on Linux/macOS
- **Two significance tests** — Welch's t-test (fast) or percentile bootstrap (robust)
- **Effect size guard** — uses Cohen's d so statistical noise at large N doesn't cry wolf
- **Three output formats** — rich console table, JSON (for downstream tooling), GitHub Markdown
- **PR comment automation** — posts or updates a single comment per PR; no duplicate spam

---

## Installation

```bash
pip install -e .
```

Requires Python 3.10+. Dependencies installed automatically: `click`, `numpy`, `psutil`, `requests`, `rich`, `scipy`.

---

## Quick Start

### 1. Benchmark before your change

```bash
bench run "python my_script.py" \
  --label before \
  --runs  20 \
  --warmup 3 \
  --out before.json
```

### 2. Make your change, then benchmark after

```bash
bench run "python my_script.py" \
  --label after \
  --runs  20 \
  --warmup 3 \
  --out after.json
```

### 3. Compare

```bash
# Console table (default)
bench compare before.json after.json

# Choose a specific metric
bench compare before.json after.json --metric wall_s

# Bootstrap instead of t-test
bench compare before.json after.json --stat bootstrap

# Markdown report to file
bench compare before.json after.json --output markdown --report-out report.md

# JSON for downstream tooling
bench compare before.json after.json --output json --report-out summary.json
```

Exit code is `0` for no-change/improvement and `1` for a regression — safe to use in CI `if` conditions.

---

## CLI Reference

### `bench run`

```
bench run COMMAND [OPTIONS]

  COMMAND   Shell command to benchmark (quote it).

Options:
  -l, --label TEXT    Label for this result set.  [default: benchmark]
  -n, --runs INTEGER  Number of timed measurement runs.  [default: 20]
  -w, --warmup INT    Number of un-timed warmup runs.  [default: 3]
  -o, --out PATH      Output JSON path.  [default: <label>.json]
```

### `bench compare`

```
bench compare BEFORE_JSON AFTER_JSON [OPTIONS]

Options:
  --stat [ttest|bootstrap]          Statistical test.  [default: ttest]
  --alpha FLOAT                     p-value threshold.  [default: 0.05]
  --min-effect FLOAT                Min |Cohen's d|.  [default: 0.2]
  --metric [wall_s|cpu_s|peak_rss_mb|all]   [default: all]
  -f, --output [console|json|markdown]      [default: console]
  --report-out PATH                 Write report to file (json/markdown).
```

### `bench comment`

```
bench comment REPORT_MD [OPTIONS]

  Post or update a PR comment with a Markdown report.

Options:
  --repo TEXT    GitHub repo as owner/name.  [env: GITHUB_REPOSITORY]
  --pr INTEGER   Pull request number.        [env: PR_NUMBER]
  --token TEXT   GitHub token.               [env: GITHUB_TOKEN]
```

---

## How the regression decision works

A change is flagged as a **REGRESSION** only when **both** conditions hold:

| Condition | Default threshold | What it guards against |
|---|---|---|
| p-value < α | 0.05 | Random noise producing a false alarm |
| \|Cohen's d\| ≥ min_effect | 0.2 | Statistically significant but practically irrelevant micro-differences at large N |

This means 20 ms slower on a 10-second operation (d ≈ 0.01) won't fire, but 20 ms slower on a 50 ms operation (d ≈ 1.8) will.

---

## GitHub Actions integration

Copy [`.github/workflows/benchmark.yml`](.github/workflows/benchmark.yml) into your repo.

### Option A — configure in the workflow file

Edit the `default:` values under `workflow_dispatch.inputs`.

### Option B — `.benchmark.env` file (recommended)

Create a `.benchmark.env` in your repo root (copy from `.benchmark.env.example`):

```bash
BENCH_COMMAND=python src/my_script.py
BENCH_RUNS=20
BENCH_WARMUP=3
BENCH_STAT=ttest
BENCH_ALPHA=0.05
BENCH_MIN_EFFECT=0.2
```

The workflow loads this automatically. The file is gitignored by default — add it if you want the config checked in.

### What the workflow does on each PR

1. Installs the harness
2. Checks out the **base branch** → runs `bench run` → `before.json`
3. Checks out the **PR branch** → runs `bench run` → `after.json`
4. Runs `bench compare` → generates `report.md`
5. Uploads `before.json`, `after.json`, `report.md` as artifacts (kept 14 days)
6. Posts or updates a single PR comment with the Markdown report
7. **Fails the CI check** if a regression is detected

The PR comment is always updated in place (never duplicated), identified by a hidden HTML marker.

### Required permissions

The workflow uses `GITHUB_TOKEN` (built into every Actions run — no setup needed) with `pull-requests: write` to post comments.

---

## Example PR comment

> ## 🔴 Benchmark Report — `base (main)` → `pr (feature/fast-path)`
>
> **Overall verdict: REGRESSION**
>
> | Metric | Before | After | Δ% | p-value | Cohen's d | Verdict |
> |--------|-------:|------:|---:|--------:|----------:|---------|
> | Wall time | 0.1050 s | 0.2180 s | +107.62% | 0.0000 | +9.341 | 🔴 REGRESSION |
> | CPU time | 0.0000 s | 0.0000 s | +0.00% | 1.0000 | +0.000 | ⚪ NO_CHANGE |
> | Peak RSS | 13.17 MB | 13.67 MB | +3.80% | 0.0001 | +3.975 | 🔴 REGRESSION |

---

## Agentic mode — `bench optimize`

An agent loop where **the harness is the objective judge**: an LLM proposes a fix, the harness verifies it, and the agent retries with the measured numbers if they don't improve.

```
        ┌────────────┐  new file   ┌──────────────────────────────┐
        │  Proposer  │────────────▶│ 1. stdout identical?         │──no──┐
        │ (Claude)   │             │ 2. bench: significant        │──no──┤
        └─────▲──────┘             │    wall-time IMPROVEMENT,    │      │
              │                    │    no regression elsewhere?  │      │
              │ rejected attempts  └──────────────┬───────────────┘      │
              │ + p-value, Δ%, d                  │ yes                  │
              └───────────────────────────────────┼──────────────────────┘
                                                  ▼    revert file + retry
                                   keep the change, stop (≤ max-iterations)
```

```bash
# Real agent (needs `pip install -e ".[agent]"` and ANTHROPIC_API_KEY)
cp examples/slow_version.py work.py
bench optimize work.py -c "python work.py" --max-iterations 5

# Free real agent: a local model via Ollama (no key, no cost, nothing leaves your machine)
#   1. install from https://ollama.com   2. ollama pull qwen2.5-coder:7b
bench optimize work.py -c "python work.py" --proposer ollama
bench eval examples/tasks --proposer ollama --model qwen2.5-coder:7b   # set OLLAMA_HOST for a remote server

# Offline demo, no API key: replays examples/candidates/ (wrong output → no gain → real fix)
bench optimize work.py -c "python work.py" --proposer scripted --candidates examples/candidates
```

Design notes:
- **Two gates, both objective.** Correctness (identical stdout) comes before speed, so "fast but wrong" is never accepted. Speed uses the same Welch/bootstrap + Cohen's d rule as `bench compare`.
- **Feedback, not just retry.** Each retry prompt includes every rejected attempt with its Δ%, p-value and effect size.
- **Always reversible.** Rejected candidates, crashes and Ctrl-C all restore the original file.
- **Pluggable proposer.** `Proposer` is a one-method protocol with three implementations: Claude (paid API), Ollama (free, local) and scripted (offline, deterministic). The loop is verified without network access, and swapping models is a flag, so models can be compared with `bench eval`.
- **Caveats.** It executes model-written code (use a scratch copy). Timing is noisy on busy machines — a noisy baseline can cause false rejections, so raise `--runs` if you see them.

### Evaluating the agent — `bench eval`

Agents should be measured, not eyeballed. `bench eval` runs the optimiser over every task in a folder (each task = `slow.py` + optional `candidates/`) in a scratch copy and reports **solve rate** and **mean attempts to solve**:

```bash
bench eval examples/tasks --proposer scripted   # deterministic, offline (CI-safe)
bench eval examples/tasks --proposer anthropic  # real model; compare models/prompts by these two numbers
```

```
│ duplicates  │  yes   │        2 │  -69.3% │
│ fibonacci   │  yes   │        2 │  -50.6% │
│ sum_squares │  yes   │        2 │  -47.8% │
Solve rate: 100%   Mean attempts to solve: 2.0
```

The scripted run validates the *harness* (every task's wrong candidate must be rejected, the real fix accepted); the Anthropic run measures the *agent*. Add a task by creating `examples/tasks/<name>/slow.py`.

---

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

51 tests covering the runner, statistics engine, reporter, GitHub commenter (HTTP calls mocked), the CLI, and the agent loop (scripted and mocked-Ollama proposers).

---

## Known limitations

- **CPU time on Windows** — `psutil` cannot reliably capture CPU time for short-lived subprocesses on Windows. Wall time and peak RSS are accurate on all platforms.
- **Single-command benchmarks only** — the harness measures one command per `bench run`. To benchmark multiple targets, run `bench run` and `bench compare` once per target.
- **Same environment assumption** — base and PR branches are benchmarked sequentially on the same runner, so transient system load can affect results. Use enough runs (≥ 20) to smooth this out.
