# PolluTrace

Execution-grounded multi-agent localization and repair of order-dependent (OD) flaky tests.
AI4015 Agentic AI, Fall 2026, FAST-NUCES Islamabad. Zoya Ahmad and Zarpash Nasim.

This repository holds the Phase 1 technical foundation: the IDoFT data pipeline, a
reproducible test-order runner, patch validation, and baselines **B1** (single LLM call)
and **B2** (iFixFlakies), with their results on the development set.

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
# B1 needs an LLM key: set GEMINI_API_KEY (default model gemini-2.5-flash), or see pollutrace/llm.py
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

## Layout

```
java/OrderRunner.java     runs pkg.Cls#method lists in one JVM (JUnit 3/4/5 via reflection); lists tests
pollutrace/env.py         portable toolchains, paths, subprocess helper
pollutrace/project.py     clone at SHA, build, pathing-jar classpath, run orders, patch/revert
pollutrace/validate.py    failing-order check, N randomized orders, assertion-integrity check
pollutrace/llm.py         provider-agnostic OpenAI-compatible client (Gemini by default)
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
