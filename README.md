# PolluTrace

Execution-grounded multi-agent localization and repair of order-dependent (OD) flaky tests.
AI4015 Agentic AI, Fall 2026, FAST-NUCES Islamabad. Zoya Ahmad and Zarpash Nasim.

Phase 1 built the technical foundation: the IDoFT data pipeline, a reproducible test-order
runner, patch validation, and baselines **B1** (single LLM call) and **B2** (iFixFlakies).
Phase 2 adds the PolluTrace multi-agent system, the NIODebugger-style base-paper pipeline,
and the experiments E1–E6.

## Changes since Phase 1

| Area | Phase 1 | Phase 2 |
|---|---|---|
| System | baselines only | supervisor + 4 agents: localizer (G1), state diff (G2), repair, validator (G3) |
| Ablation | – | every gap component can be switched off (`pollutrace/config.py` presets) |
| Base paper | – | B4: NIODebugger-style pipeline re-implemented in our harness (`baselines/b4_niodebugger.py`) |
| Inputs to systems | B1: confirmed failing pair | all systems get the same fixed failing order (30 module tests + hidden polluter + victim) and its trace; never the IDoFT polluters |
| Evaluation | per-baseline scripts | one harness for all systems (`pollutrace/harness.py`): same final check, 3 runs, mean ± std |
| Logging | dossier per victim | plus full trajectories (every LLM call, test run, compile, decision) in `logs/trajectories/` |
| Test set | 75 held-out victims | fixed subset `data/test_subset.csv` (rule in `scripts/make_subset.py`) so 3 runs fit the time budget |
| Integrity check | assertions, ignore, early return | also swallowed exceptions; checks the polluter file when it is patched |

## Architecture (Phase 2)

```
failing order + trace
        │
   Supervisor (pollutrace/supervisor.py)  budgets: LLM calls, test runs, wall time
        │
        ├─► Localizer (G1)   static shared-state ranking + LLM re-rank → confirm by execution
        │                    (singles, then groups of 8 with bisection)        → polluter
        ├─► State diff (G2)  OrderRunner `state`: static fields + system properties after
        │                    a clean JVM vs. after the polluter                  → what changed
        ├─► Repair           LLM edits the victim or the polluter test class, using all of the above
        │        ▲
        │        │ feedback (compile errors, new failures, integrity issues)
        └─► Validator (G3)   integrity → failing order → after each polluter → alone → N=20 random orders
                 │ a failing random order → back to the localizer for a second polluter (backtracking)
                 ▼
         accepted patch → harness final evaluation (IDoFT ground truth, N=100 orders)
```

## Requirements

* Python 3.9+ (standard library only, no pip install needed)
* Git
* Internet access to GitHub, Maven Central, api.adoptium.net and the LLM provider

`scripts/setup_tools.py` downloads portable **JDK 8, 11, 17** (Eclipse Temurin) and
**Maven 3.6.3 / 3.9.9** into `../work/tools`, so the machine's own Java is never used.
Each project is built with the oldest JDK that works (8 → 11 → 17), and the choice is
recorded. Works on Windows, Linux and macOS.

## Run the baseline

```bash
git clone https://github.com/zoyaahmad428/PolluTrace.git
cd PolluTrace
python run_phase1.py setup manifest reproduce split   # data pipeline (hours: builds 20 projects)
# B1 needs an LLM key: set GEMINI_API_KEY (model auto-discovered), or see pollutrace/llm.py
python run_phase1.py probe b1 b2 summary
```

Each step resumes where it stopped. Logs go to `../work/logs/`; results go to `results/`.

| Step | Script | Output |
|---|---|---|
| setup | `scripts/setup_tools.py` | portable JDKs, Maven, compiled `OrderRunner` |
| manifest | `scripts/build_manifest.py` | `data/manifest.csv`: 135 IDoFT OD victims with known polluters (20 projects) |
| reproduce | `scripts/reproduce.py` | `results/reproduction.csv`: clone, build, victim-alone ×2, polluter→victim ×2 |
| split | `scripts/split.py` | `data/dev_set.csv` (15 victims, ≤3 per project), `data/test_set.csv` |
| probe | `scripts/probe_orders.py` | `results/probe_orders.csv`: failure rate of unpatched victims in random orders, s/order |
| b1 | `baselines/b1_single_call.py` | `results/b1_single_call.csv`, `results/dossiers/B1/*.json` |
| b2 | `baselines/b2_ifixflakies.py` | `results/b2_ifixflakies.csv` |
| summary | `eval/summarize.py` | `results/summary.md` |

## Phase 2: run PolluTrace and the experiments

Same requirements as Phase 1 (Python 3.9+, standard library only; `requirements.txt` lists
optional test tools). Configure the LLM with environment variables (see `.env.example`):

| Variable | Meaning |
|---|---|
| `POLLUTRACE_LLM_API_KEY` | API key (or `GEMINI_API_KEY`, or a key file at `../work/secrets/llm_key.txt`) |
| `POLLUTRACE_LLM_BASE_URL` | OpenAI-compatible endpoint; default Gemini |
| `POLLUTRACE_LLM_MODEL` | model id; empty = newest available "flash" model, recorded in every result row |
| `POLLUTRACE_WORK` | work folder for toolchains and checkouts (default `../work`) |

```bash
python scripts/make_subset.py                    # data/test_subset.csv (fixed rule, before any run)
python -m unittest discover -s tests -t .        # unit tests (no Java needed)
python experiments/e1_baselines.py               # E1  B1 x3 runs, B2 x1
python experiments/e2_base_paper.py              # E2  NIODebugger-style pipeline x3
python experiments/e3_pollutrace.py              # E3  full PolluTrace x3
python experiments/e4_g1_localization.py         # E4  G1: executions to find the polluter
python experiments/e4_g2_statediff.py            # E4  G2: with vs without the state diff (= E3 vs A2)
python experiments/e4_g3_validator.py            # E4  G3: seeded bad patches, strict vs weak validator
python experiments/e4_g3_validator.py --sweep    #     G3: false fixes caught within N orders
python experiments/e5_ablation.py                # E5  A1 no localizer, A2 no state diff, A3 weak validator
python experiments/e6_efficiency.py              # E6  tokens, time, test executions, run-to-run variation
python eval/stats.py                             # all tables (mean ± std over runs) -> results/phase2_tables.md
python eval/failure_analysis.py                  # failure categories, 2 success + 2 failure trajectories
```

Every experiment accepts `--set`, `--runs`, `--shard i/k` (split projects across machines),
`--limit` and `--ids` (smoke tests), `--n-final` and `--final-secs`. Each step resumes where it
stopped. Outputs: `results/<E>/<system>/run<k>.csv`, dossiers next to them, trajectories in
`logs/trajectories/`.

### Protocol

* Prompts and budgets were set on the 15-victim development set only; the test subset is never used for tuning.
* 3 independent runs per LLM system (temperature 0.2); seeds are derived from victim id and run number.
* Final evaluation is identical for every system: victim after every known IDoFT polluter,
  assertion integrity, and 100 randomized orders (15-minute cap per victim).

### Gap-resolution table

From `results/phase2_tables.md` (`eval/stats.py`). Phase 2 run: 1 run per system on the free Gemini
tier (`gemini-3.5-flash-lite`, recorded in every result row), 15-victim test subset, of which 12
were attempted (V116, V122, V129 in WildFly `naming` do not fail in the constructed order, for any system).

| Gap | Component | Base paper (B4) | PolluTrace | Evidence | Addressed? |
|---|---|---|---|---|---|
| G1: polluter search is blind / expensive | Localizer | no localization step | known polluter found in 2.1 order runs on average (one-by-one 20.0, bisection 9.2); fix rate 58.3% with vs 50.0% without | E4-G1, E5 A1 | Partially |
| G2: repair lacks the actual polluted state | State diff | repair from source only | diff shows a changed field for 12/15 victims; fix rate 58.3% with vs 58.3% without | E4-G2, E5 A2 | Not |
| G3: "passes once" accepts false fixes | Validator | accepts after the failing order passes | seeded bad patches rejected 47/47 (weak 30/47); false-fix rate 0.0% vs 12.5% with the weak validator | E4-G3, E5 A3 | Fully |

Overall fix rate: PolluTrace 7/12 (58.3%), B4 7/12, B1 4/12. PolluTrace costs more per victim
(3.3 LLM calls and 304 test executions vs 1.8 and 94 for B4); see E6.

## Layout

```
java/OrderRunner.java     runs pkg.Cls#method lists in one JVM (JUnit 3/4/5 via reflection); lists tests
pollutrace/env.py         portable toolchains, paths, subprocess helper
pollutrace/project.py     clone at SHA, build, pathing-jar classpath, run orders, patch/revert
pollutrace/validate.py    failing-order check, N randomized orders, assertion-integrity check
pollutrace/llm.py         provider-agnostic OpenAI-compatible client (Gemini by default)
pollutrace/config.py      system configurations and ablation presets
pollutrace/harness.py     shared experiment loop, fixed failing orders, final evaluation, B1 as a system
pollutrace/trajectory.py  trajectory logging, LLM/test/compile accounting, budgets
pollutrace/static_state.py  static shared-state analysis of Java test sources
pollutrace/agents/        localizer (G1), validator (G3), state diff (G2), repair
pollutrace/supervisor.py  orchestration: budgets, repair loop, backtracking
experiments/              E1–E6 scripts
tests/                    unit tests (fake project, no Java)
docs/devlog.md            development log: failures, changes, effects
baselines/                B1 single LLM call, B2 iFixFlakies (built from source)
contracts/                JSON schemas: flakiness dossier, tool interfaces
eval/summarize.py         tables for the report
data/, results/           manifest, splits, raw CSVs, dossiers, summary
```

## Definitions used in results

* **Reproduced**: the victim passes alone (twice) and fails right after a known polluter (twice).
* **Fix**: after the patch, the victim passes right after its confirmed polluter.
* **Accepted**: fix and the assertion-integrity check passes (no skips, no fewer assertions).
* **False fix**: an accepted patch whose victim fails at least once in N randomized orders.
  Each order is a random permutation of the victim, all its known polluters and 20 other
  tests from the module, run in one fresh JVM.

Known polluters (IDoFT ground truth) are used only for evaluation. No system under test sees them.
