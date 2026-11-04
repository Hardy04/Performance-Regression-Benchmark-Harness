# Interview prep: Performance Regression Benchmark Harness + optimisation agent

(Personal notes. Gitignored. Do not commit.)

## 30-second pitch

"I built a CLI that detects performance regressions with real statistics: Welch's t-test or bootstrap, plus
Cohen's d so tiny differences don't trigger false alarms. It posts results as a PR comment and gates CI.
Then I added an agent on top: an LLM proposes a fix to a slow file, and the harness acts as an objective judge.
The change is kept only if the output is identical and the speedup is statistically significant. Otherwise it's
reverted and the model retries with the measured numbers. I also built an eval suite that scores the agent by
solve rate and attempts-to-solve, and wired it into CI."

## Say this before they ask (honesty is a strength here)

- The offline eval uses scripted candidates, so it proves the *harness* is sound, not that the *model* is good.
- Fill in before the interview: **run `bench eval --proposer ollama` once and write your real numbers here:**
  solve rate = ____, mean attempts = ____, model = ____. Never quote numbers you haven't measured.
- Correctness = same stdout. That's a known gap (see below), and I know what I'd do about it.

## Likely questions

**Why is this an "agent" and not just an LLM call?**
It's a closed loop with feedback: act (edit the file), observe (run correctness + benchmark), decide
(accept/reject), and adapt (the next prompt includes what failed and the measured numbers). It has a stopping
condition and a guaranteed rollback.

**Why not let the model judge its own change?**
Models are confidently wrong. The verifier is deterministic code with statistics, independent of the proposer,
so a weaker or hallucinating model can't land a bad change. It can only waste attempts.

**Why both a p-value and Cohen's d?**
With many runs, tiny differences become "significant". The p-value says the difference is real; the effect
size says it's big enough to matter. Requiring both avoids false alarms and ignores irrelevant noise.

**How do you handle flaky timing?**
Warmup runs, N≥10 samples, significance testing instead of comparing means, and an effect-size floor. A noisy
machine can reject a good fix (I saw this) but cannot accept a bad one, so it fails safe. Next step: interleave
baseline and candidate runs and re-measure borderline results.

**What stops the agent breaking the code?**
Gate 1 requires exit code 0 and byte-identical stdout; gate 2 rejects any regression, including memory. The
original file is restored on any failure or interrupt. Gap: stdout equality isn't a test suite, so I'd add a
`--test-cmd` gate.

**Security?**
It runs model-written code, so it should be sandboxed (container, no network, resource limits). Currently the
README says to use a scratch copy. I treat that as the main production gap.

**How did you test an LLM feature without calling an LLM?**
The proposer is a one-method interface. Tests and CI use a scripted proposer (deterministic), and the Ollama
proposer is tested against mocked HTTP. Live models are measured separately via `bench eval`.

**How would you improve it?**
(1) Test-suite correctness gate. (2) Tool use: let the model profile and run tests before proposing.
(3) Multi-file edits. (4) Sandbox. (5) Compare models with eval, logging cost per solved task.

**A bug you hit?**
My first fibonacci "wrong" candidate was actually correct, so the harness accepted it. The harness was right
and my test data was wrong. Also a flaky test: an identical-speed candidate occasionally looked "improved" by
chance with 5 noisy runs, so I replaced it with a deterministic clearly-slower candidate.

## Demo script (2 minutes, free, offline)

```
bench optimize work.py -c "python work.py" --proposer scripted --candidates examples/candidates
```
Point out: attempt 1 rejected (wrong output), attempt 2 rejected (no significant gain), attempt 3 accepted
(-44%, p<0.0001). Then `bench eval examples/tasks --proposer scripted` and the green CI run on GitHub.
