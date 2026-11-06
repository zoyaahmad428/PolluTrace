# Development log

What went wrong, what we changed and what effect it had. Newest entries at the bottom of each
phase. Commit hashes refer to this repository.

## Phase 1 (infrastructure and baselines)

| # | Problem observed | Change | Effect |
|---|---|---|---|
| 1 | Windows command line too long for project classpaths (32k limit) | Pathing jar with a manifest `Class-Path` (`project._pathing_jar`) | Every project runs with one short `-cp` argument, on Java 8 too |
| 2 | Activiti and others failed with a missing parent POM; error summary showed only the last `[ERROR]` line | `_err_summary` puts `[FATAL]` lines first | Build failures classified by root cause in `reproduction.csv` |
| 3 | Four Dubbo victims failed even alone on JDK 17 (module access) | `--add-opens` for JDK 11/17 runs, plus a `retry` step | All four reproduced |
| 4 | The laptop went to sleep and killed overnight runs | `keep_awake()` (Windows `SetThreadExecutionState`) in the pipeline runner | Runs survive the night |
| 5 | The order probe hung for hours on admiral (429 s per order) | 15-minute budget per victim for randomized orders (`validate.MAX_SECS`) | Probe finished; capped victims report how many orders ran |
| 6 | `gemini-2.5-flash` returned 404 for a new key (retired model) | `llm._discover()` picks the newest "flash" model the key can use | No hard-coded model names; the model is logged per row |
| 7 | HTTP 503 "model overloaded" for long periods | After 3 retries, fall back to the next model and keep the one that answered (`_promote`) | B1 completed; model recorded per victim |
| 8 | Free-tier daily quota exhausted mid-run (HTTP 429) | Resume logic: rows with `llm_error` are retried on the next run | Finished after the daily reset |
| 9 | A killed run left a patched test file, so the next run saw "not failing" | Baselines restore a dirty checkout before starting | V055 re-run correctly |
| 10 | iFixFlakies: `.dtfixingtools` folder missing | Create it before running | Tool starts |
| 11 | iFixFlakies on Windows: deletes temp files that are still open | Run B2 inside Linux containers (`maven:*` images), same checkout and Maven cache | B2 runs on the Windows laptop |
| 12 | iFixFlakies needs surefire reports for the original order; our builds skip tests | Run the module's suite once with failures ignored | Original order available |
| 13 | Stale empty `original-order` made iFixFlakies say "Module has no tests" | Clear `.dtfixingtools` once per module | Fixed for JUnit 4 modules; JUnit 3-style suites (Struts) remain a tool limitation |

## Phase 2 (agents and experiments)

| # | Problem observed | Change | Effect |
|---|---|---|---|
| 14 | B1 was given the confirmed polluter pair, which a real developer does not have | Every system now receives the same fixed failing order (30 module tests + hidden polluter + victim) and its trace (`harness.failing_order`) | Localization is part of the task; inputs identical across systems |
| 15 | Static ranking alone ties many suspects (no shared static members) | Ties broken by distance to the victim; optional LLM re-rank of the top 15 (`cfg.llm_rank`) | Measured in E4-G1 (ranked_static vs ranked_llm) |
| 16 | Group testing can miss pollution that needs two tests together | Bisection returns "no single polluter" instead of a wrong answer; supervisor then repairs without a polluter | No false polluter reported |
| 17 | Snapshot values differed between JVMs because of identity hash codes in `toString()` | `OrderRunner.repr` describes collections, maps, arrays and plain objects field by field, never by identity | Only real changes appear in the state diff |
| 18 | System properties such as `sun.java.command` always differ between the two snapshot JVMs | `statediff.NOISE` filter | Diff shows only properties the polluter set |
| 19 | A patch can fix the found polluter while another polluter still breaks the victim | Validator returns the failing randomized order; supervisor localizes a second polluter in it and retries (backtracking) | Measured as category `second_polluter` in the failure analysis |
| 20 | Mutants such as `@org.junit.Ignore` (fully qualified) passed the integrity check | `SKIP_RE` accepts qualified annotations; new check for `catch (Throwable) {}` | All four seeded mutant kinds flagged in unit tests |
| 21 | The 75-victim test set at 3 runs x 6 systems does not fit the time budget | Fixed subset rule written before any Phase 2 run (`scripts/make_subset.py`) and `--shard` to split projects across two laptops | Reported as a limitation |

Add new rows as the Phase 2 runs reveal problems (what failed, the fix, and the measured effect).
