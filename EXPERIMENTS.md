# Experiment log

All benchmark tuning will use the development split only. The test split will
remain untouched until the final evaluation.

## Setup attempt: package-directory-only vendoring

- **Hypothesis:** Copying the upstream `toolz/` package directory is sufficient
  to run the full upstream test suite from the vendored tree.
- **Change:** Vendored `toolz/` from tag `1.1.0` and ran its tests under Python
  3.11.15 with pytest 8.4.2.
- **Result:** 184 tests passed and 2 failed in 1.07 seconds. The failures exposed
  two packaging assumptions: the suite imports the upstream `tlz` alias, and
  `toolz.__version__` reads installed distribution metadata.
- **Decision:** **REVERT.** The package-directory-only layout was incomplete.
  Vendor the upstream `tlz` alias and minimal version metadata as well.

## Feasibility: full-suite execution

- **Hypothesis:** The complete `toolz` suite runs below the five-second cutoff,
  so every mutant can use the same complete test command.
- **Change:** Vendored `toolz` 1.1.0 source, `tlz` alias, tests, license, and
  version metadata. Ran the complete suite and the deterministic AST site scan.
- **Result:** All 186 tests passed in 0.63 seconds of pytest time and 1.11
  seconds wall-clock time. The production source has 155 functions and methods
  and 1,040 candidate mutation sites.
- **Decision:** **KEEP.** Use the complete suite during harvesting. This avoids
  test-selection logic while remaining comfortably below the cutoff on the
  measured machine.

The independent reproduction completed all 186 tests in 0.22 seconds and
matched the function and mutation-site counts exactly.

## Harvest attempt: raw pytest output

- **Hypothesis:** Pytest output is stable when the mutation itself and test
  order are fixed.
- **Change:** Ran a small harvest in a randomly named temporary copy.
- **Result:** Test order and failures were stable, but some tracebacks included
  the temporary directory name, runtime text, and process-specific object
  addresses.
- **Decision:** **REVERT.** Raw output would make regenerated cases differ.
  Normalize the temporary root, elapsed-time strings, and object addresses
  before parsing or storing output. Set `PYTHONHASHSEED` to zero as well.

## Harvest attempt: qualified-name-only function IDs

- **Hypothesis:** Sampling 400 mutants with at most four per function will
  produce the target range of 200–400 killed cases without allowing large
  functions to dominate.
- **Change:** Enumerated source-changing mutations, deduplicated identical
  output, sampled with seed 1729, and ran the complete suite in an isolated
  copy with a 10-second timeout.
- **Result:** The enumerator found 1,107 unique mutants. Of 400 executed
  mutants, 371 were killed, 28 survived, 1 timed out, and 0 were invalid. An
  integrity test then found that `memoize` defines several conditional nested
  functions all named `key`. Their qualified names collide, so three distinct
  source functions had the same candidate ID.
- **Decision:** **REVERT.** Exact source labels require a unique candidate ID.
  Add the definition line to every function ID and regenerate the sample and
  cases from scratch.

## Harvest: line-qualified, function-balanced sample

- **Hypothesis:** A module, qualified name, and definition line uniquely
  identify every candidate function while remaining stable for the pinned
  target.
- **Change:** Added the definition line to function IDs, reran deterministic
  sampling with seed 1729, and executed the complete harvest again.
- **Result:** The enumerator found 1,107 unique mutants. The sampler covered 153
  functions. Of 400 executed mutants, 372 were killed, 27 survived, 1 timed
  out, and 0 were invalid. The resulting split has 75 functions and 186 cases
  on each side. Integrity checks found no function overlap, missing function
  chunks, missing failing-test source, or temporary-path leakage.
- **Decision:** **KEEP.** The 372 committed cases have unique candidate IDs and
  exact line-level mutation provenance. Preserve all non-killed outcomes in
  `data/mutants.jsonl`.

## Harvest attempt: 10-second timeout

- **Hypothesis:** A 10-second hard timeout cleanly separates terminating
  mutants from hangs.
- **Change:** Regenerated the same 400-mutant sample independently.
- **Result:** One import-related mutant finished near the cutoff. It timed out
  in one run but completed as killed in the independent reproduction, changing
  the dataset from 372 to 373 cases despite identical code and seed. Isolated
  runs completed in 9.75 and 9.76 seconds with a 20-second limit.
- **Decision:** **REVERT.** Ten seconds creates a process-scheduling race rather
  than a stable label for this mutant.

## Harvest: 20-second timeout

- **Hypothesis:** A 20-second hard cutoff gives the borderline terminating
  mutant enough margin while still bounding genuine hangs.
- **Change:** Raised only the subprocess timeout and regenerated the unchanged
  deterministic sample.
- **Result:** Of 400 mutants, 373 were killed, 27 survived, 0 timed out, and 0
  were invalid. The split contains 75 functions on each side, producing 187
  development cases and 186 test cases.
- **Decision:** **KEEP.** Use 20 seconds as the hard timeout for reproducible
  harvesting.

## Harness validation: stable candidate order

- **Hypothesis:** A deterministic function-ID-order ranking should perform poorly
  while exercising the complete evaluation path before any real localizer is
  implemented.
- **Change:** Built the original-code function index, per-case mutated-function
  overlay, full-ranking validator, token counter, metric aggregation, fixed-seed
  bootstrap intervals, paired comparison routine, and breakdowns. Evaluated a
  stable-order sanity ranking on the development split only.
- **Dev result:** Across 187 cases and 155 candidates, Top-1 was 0%, Top-5 was
  4.813%, MRR was 0.036, median rank was 80, and median tokens-to-hit was 7,531.
- **Decision:** **KEEP the harness, not the ranking.** The deliberately weak
  ranking produces plausible floor behavior and the test split remains locked.

## Metric mutation check: reciprocal-rank off-by-one

- **Hypothesis:** The hand-built metric examples should reject a reciprocal
  rank implementation using `1 / (rank + 1)`.
- **Change:** Ran the same metric contract against the correct implementation
  and a deliberately broken off-by-one implementation.
- **Dev result:** The correct implementation passed all known-rank examples;
  the deliberately broken implementation raised the expected assertion.
- **Decision:** **KEEP.** Retain the mutation check in the normal test suite so
  a denominator regression cannot silently change MRR.

## Baseline attempt: strict stack-frame parser

- **Hypothesis:** Parsing traceback lines containing `path.py:line: in function`
  will recover library frames for runtime exceptions.
- **Change:** Implemented deepest-library-frame-first ranking with a stable
  candidate-order fallback.
- **Dev result:** Top-1 was 2.139%, Top-5 was 6.952%, and MRR was 0.057. Only 6
  of 90 non-assertion cases yielded a parsed library frame.
- **Decision:** **REVERT.** Pytest's stored long-traceback format normally uses
  `path.py:line:` without the literal `in function`, so the parser was measuring
  a format mismatch rather than the heuristic.

## L0: deterministic random

- **Hypothesis:** A fixed per-case shuffle provides a reproducible sanity floor.
- **Change:** Seeded each case from seed 2027 and its case ID, then returned a
  full permutation of all 155 candidates.
- **Dev result:** Top-1 was 0%, Top-5 was 2.139%, MRR was 0.030, median rank was
  76, and median tokens-to-hit was 9,491.
- **Decision:** **KEEP.** This is the reproducible floor for later comparisons.

## L1: corrected stack-frame heuristic

- **Hypothesis:** Reading pytest's actual `path.py:line:` frames and ranking the
  deepest library function first will help runtime exceptions but not ordinary
  assertion failures.
- **Change:** Added the observed pytest frame format, excluded tests and
  site-packages, and retained stable fallback ordering.
- **Dev result:** Top-1 was 26.738%, Top-5 was 30.481%, MRR was 0.299, median
  rank was 34, and median tokens-to-hit was 4,041. Top-1 was 0% on 97 assertion
  cases and 55.556% on 90 other cases.
- **Decision:** **KEEP.** The error-type split matches the expected failure mode
  and gives Phase 4 routing a concrete target.

## L2: code-aware BM25

- **Hypothesis:** Exception text, tracebacks, and failing-test source contain
  identifiers that lexical retrieval can match to the mutated function.
- **Change:** Indexed qualified name, signature, docstring, and body. Queries use
  exception type, message, traceback, and failing-test source. Tokenization
  lowercases and splits snake_case and camelCase while retaining identifiers.
- **Dev result:** Top-1 was 36.898%, Top-5 was 57.219%, MRR was 0.469, median
  rank was 3, median tokens-to-hit was 617, and p50 latency was 18.3104 ms.
- **Decision:** **KEEP.** BM25 is the strongest Phase 3 baseline.

## L3: optional dense retrieval availability

- **Hypothesis:** The baseline command should remain usable without downloading
  an embedding model.
- **Change:** Put `BAAI/bge-small-en-v1.5` behind `--dense` and the pinned
  `fastembed` optional extra. Probe the model before evaluation and report a
  skip reason on any dependency, download, or runtime failure.
- **Dev result:** The lean environment reported `ModuleNotFoundError` for the
  intentionally uninstalled `fastembed` extra and continued with L0, L1, L2,
  and L4. No dense quality number was generated.
- **Decision:** **KEEP.** Dense remains available as an opt-in experiment and
  cannot break the default CPU-only Replit run.

## L4: equal-weight reciprocal-rank fusion

- **Hypothesis:** Fusing stack and BM25 rankings with RRF at `k=60` will combine
  complementary traceback and lexical evidence.
- **Change:** Fused complete L1 and L2 rankings. Dense joins the fusion only when
  the optional model is available.
- **Dev result:** Top-1 was 27.273%, Top-5 was 45.455%, MRR was 0.376, median
  rank was 7, and median tokens-to-hit was 967. BM25 exceeded hybrid MRR by
  0.093 with paired 95% interval [0.028, 0.156].
- **Decision:** **KEEP AS A REPORTED BASELINE, NOT AS THE WINNER.** Equal-weight
  fusion dilutes BM25 with unhelpful stack rankings on assertion failures. Do
  not tune the baseline until it wins.

## A5: failing-test direct-call boost

- **Hypothesis:** Direct library calls in the failing test are especially useful
  when an assertion traceback never enters the buggy function.
- **Change:** Parsed each failing test with `ast`, resolved imported aliases and
  call names, moved matching function candidates ahead of the BM25 ranking, and
  preserved BM25 order within both groups.
- **Dev result:** Top-1 was 44.385%, Top-5 was 64.706%, MRR was 0.543, median
  rank was 2, and median tokens-to-hit was 354. Compared with BM25, MRR improved
  by 0.073 with paired 95% interval [0.042, 0.107].
- **Decision:** **KEEP.** Direct calls add complementary signal without model
  downloads or a large latency penalty.

## A6: exception-aware routing

- **Hypothesis:** Use stack ranking only when the error is not an assertion and
  a library frame exists; otherwise use A5. This should preserve assertion-case
  retrieval while avoiding BM25 work on informative runtime traces.
- **Change:** Added the pre-registered exception-and-frame routing rule. No
  thresholds or weights were tuned.
- **Dev result:** Top-1 was 54.545%, Top-5 was 65.241%, MRR was 0.603, median
  rank was 1, median tokens-to-hit was 251, and p50 latency was 11.0817 ms.
  Against A5, MRR improved by 0.061 [0.018, 0.101] and p50 latency decreased by
  7.513 ms [4.660, 9.920]. Against always-on L4 hybrid, MRR improved by 0.227
  [0.168, 0.289] and p50 latency decreased by 7.189 ms [4.405, 8.960].
- **Decision:** **KEEP.** This is the final development-selected approach.

## A7: BM25 query cleanup

- **Hypothesis:** Removing file paths, pytest summaries, and separator boilerplate
  will reduce lexical noise and improve BM25.
- **Change:** Cleaned only the query; the candidate corpus and tokenizer stayed
  unchanged.
- **Dev result:** Top-1 was 35.829%, Top-5 was 55.615%, MRR was 0.455, median
  rank was 4, and median tokens-to-hit was 684. Uncleaned BM25 had a paired MRR
  advantage of 0.014 [0.003, 0.027]. Cleanup was 0.948 ms faster at p50.
- **Decision:** **REVERT.** The small latency gain does not justify a significant
  quality loss. Keep it only behind `eval --experiments` to reproduce the
  negative result.

## A8: static call-graph expansion

- **Hypothesis:** Expanding top candidates through a static call graph might
  recover bugs in callers or callees.
- **Change:** Not attempted. This experiment was optional, and the three core
  attempts already established a clear winner within the one-day budget.
- **Dev result:** No run; no number reported.
- **Decision:** **REVERT FROM SCOPE.** Avoid adding implementation complexity
  without a remaining measurement need.

## Phase 5: cached dashboard validation

- **Constraint:** The Replit Run path must start in seconds and must not trigger
  harvesting or evaluation.
- **Change:** Added a read-only FastAPI dashboard over the committed result and
  case artifacts, plus leaderboard, error-breakdown, and case-explorer views.
- **Validation result:** The complete suite passed 217 tests in 2.03 seconds.
  A live server returned HTTP 200 for the homepage, health check, and cached
  results endpoint. The results endpoint reported the 187 development cases;
  the held-out test split was not evaluated.
- **Decision:** **KEEP.** The Run path serves only cached artifacts and is
  independent of the expensive benchmark pipeline.
