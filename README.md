# Where's the bug?

When a test fails, which function should a self-healing coding agent read first?
This project measures that decision on a deterministic, mutation-generated
benchmark. It ranks every function in a vendored Python library from only the
failure evidence an agent would have.

## Exact labels, without hand-labelling

The benchmark vendors `toolz` 1.1.0 at upstream commit
`568c2b8393973cd172a466546c9d95779c452438`. The harvester applies exactly one
AST mutation to one known function and runs the complete test suite. A mutation
that causes a failure becomes a benchmark case: the failure output is the query,
and the mutated function is the exact answer.

This construction avoids subjective bug-location labels. It also preserves the
mutated function body in the per-case index, so the localizer sees the code as
it existed when the test failed.

## Benchmark

The complete vendored suite contains 186 tests and ran in 0.22 seconds during
the feasibility check. The library contains 155 functions and methods across 14
source files. The deterministic syntax scan found 1,040 candidate sites, which
produced 1,107 unique source-changing mutants.

The sampler selected 400 mutants across 153 functions, with at most four per
function:

| Outcome | Mutants |
| --- | ---: |
| Killed | 373 |
| Survived | 27 |
| Timeout | 0 |
| Invalid | 0 |

The measured kill rate was 93.25%. Every mutant remains recorded in
`data/mutants.jsonl`; the 373 killed cases are committed in
`data/cases.jsonl`.

Cases were split by function, not by case. No function occurs in both splits:

| Split | Functions | Cases |
| --- | ---: | ---: |
| Development | 75 | 187 |
| Test | 75 | 186 |

All technique selection used development data. The test split was evaluated
once, after the final A6 routing rule was fixed. The CLI now refuses a second
test evaluation when `results/test_results.json` exists.

## Held-out results

Each localizer returns a complete ranking over all 155 candidates. Source cost
uses `tiktoken` with `cl100k_base`. Intervals are 95% bootstrap confidence
intervals from 1,000 resamples with seed 2027.

| Localizer | Top-1 | Top-5 | MRR | Median tokens-to-hit | p50 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| L0 random | 0.000% [0.000, 0.000] | 3.763% [1.075, 6.989] | 0.032 [0.025, 0.042] | 9,499.5 [8,624, 10,235] | 0.0209 ms [0.0208, 0.0210] |
| L1 stack | 25.806% [19.892, 31.720] | 27.419% [21.505, 33.871] | 0.281 [0.223, 0.342] | 5,651.5 [4,858, 7,211] | 0.0311 ms [0.0287, 0.0345] |
| L2 BM25 | 40.323% [33.333, 47.312] | 56.989% [49.462, 63.441] | 0.491 [0.430, 0.555] | 548.5 [378, 1,047] | 16.8660 ms [15.8305, 17.9784] |
| L4 stack + BM25 RRF | 23.118% [17.742, 29.032] | 32.796% [26.331, 39.247] | 0.308 [0.255, 0.363] | 1,958.5 [1,537, 2,184] | 17.1561 ms [15.9620, 18.1748] |
| A5 test calls | 41.935% [35.484, 48.925] | **65.591% [58.602, 72.581]** | 0.516 [0.459, 0.578] | 563.5 [469, 878] | 17.6003 ms [16.0805, 18.4290] |
| **A6 exception-aware router** | **52.151% [45.161, 59.140]** | 59.677% [52.688, 66.667] | **0.562 [0.495, 0.628]** | **530.5 [288, 893]** | **10.3861 ms [9.7183, 11.1775]** |

A6 has the strongest Top-1, MRR, median rank (1), median source cost, and p50
latency. A5 has the strongest Top-5. A6's mean rank is 23.2, worse than BM25's
14.6, because a smaller tail of difficult routed cases falls far down the
ranking. The median and reciprocal-rank metrics expose the typical behavior;
the mean rank records that failure mode rather than hiding it.

## What improved

BM25 was the strongest baseline. A5 parses the failing test, extracts direct
library calls, and moves matching candidates ahead of the BM25 order. A6 then
uses the stack heuristic only for non-assertion failures with a library frame;
all other cases use A5.

Against BM25 on the same 186 test cases, A6 improved:

- Top-1 by 11.828 percentage points, paired 95% CI [5.914, 17.742].
- MRR by 0.071, paired 95% CI [0.020, 0.123].
- p50 latency by 6.480 ms, paired 95% CI [5.184, 7.977].

The Top-5 difference was +2.688 points with interval [-3.763, 9.140], so the
test does not establish a Top-5 improvement over BM25. Compared with A5, A6
improved Top-1 by 10.215 points [4.839, 16.129] and reduced p50 latency by
7.214 ms [5.517, 8.448]. Its MRR advantage over A5 was 0.046, but the paired
interval [-0.004, 0.098] includes zero.

## What did not work

All of these decisions were made on the development split before the test run:

- Equal-weight reciprocal-rank fusion diluted BM25 with stack rankings that
  were usually unhelpful for assertions. L4 reached 0.376 development MRR versus
  0.469 for BM25; BM25's paired advantage was 0.093 [0.028, 0.156]. It remains
  reported as a baseline, not as the winner.
- Removing pytest boilerplate and paths from the BM25 query reduced development
  MRR from 0.469 to 0.455. Uncleaned BM25 led by 0.014 [0.003, 0.027]. A7 is
  retained behind `eval --experiments` for reproducibility and was not run on
  the held-out test split.
- The optional `BAAI/bge-small-en-v1.5` ONNX dense baseline was not downloaded
  in the lean environment. The evaluator skipped it cleanly rather than making
  the default run depend on a model download.
- Static call-graph expansion was left out after the three planned core
  experiments produced a clear result. No number is claimed for an experiment
  that was not run.

The full hypothesis, change, result, and KEEP/REVERT record is in
`EXPERIMENTS.md`.

## What the error split reveals

The held-out breakdown validates the routing hypothesis:

| Failure group | Cases | A6 Top-1 | A6 MRR | Median rank | Median tokens-to-hit |
| --- | ---: | ---: | ---: | ---: | ---: |
| AssertionError | 82 | 40.244% [30.488, 51.220] | 0.469 [0.374, 0.564] | 5 | 945.5 |
| Other exceptions | 104 | 61.538% [52.885, 70.192] | 0.635 [0.550, 0.722] | 1 | 260 |

Assertion tracebacks usually stop in the test after a function returns the
wrong value, so stack localization loses its main signal. Runtime exceptions
often expose a library frame, making the inexpensive stack route both faster
and more accurate. This is why a fixed per-error-type router beats always-on
fusion.

## Threats to validity

- These are synthetic, single-point mutants, not naturally occurring bugs.
- The benchmark covers one small functional-programming library.
- Real coding agents may use repository history, coverage, runtime values, or
  interactive tools that these localizers do not receive.
- Splitting by function prevents direct function leakage but also changes the
  mix of mutation operators and exception types between splits.
- Latency is local CPU wall-clock time and will vary by machine. Quality and
  token metrics are deterministic; timing is not.
- Some operator and exception subgroups are small. The dashboard separates
  groups with fewer than five cases to avoid overemphasizing their percentages.

## Reproduce

Python 3.11 and all dependencies are pinned in `pyproject.toml` and `uv.lock`.
To verify the committed artifacts and open the dashboard:

```bash
uv sync --python 3.11
uv run pytest
uv run python -m faultloc serve
```

Open `http://127.0.0.1:8000`. Replit's Run button executes the same server on
`0.0.0.0` and reads the committed cache; it does not harvest or evaluate.

To regenerate the mutation corpus and development measurements:

```bash
uv run python -m faultloc harvest
uv run python -m faultloc eval
uv run python -m faultloc eval --experiments
```

The historical final command was:

```bash
uv run python -m faultloc eval --final-test
```

It now refuses to run because the committed one-shot test artifact exists.

## Time spent

Approximately five hours, including the measurement harness, experiments,
Replit dashboard, and documentation.
