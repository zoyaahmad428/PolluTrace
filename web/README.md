# PolluTrace web console

A browser front end for the results in this repository, and a way to start a new run and
watch the agents work.

```bash
python web/server.py          # then open http://127.0.0.1:8000
python web/server.py --open   # and open the browser for you
python web/server.py --port 8080 --host 0.0.0.0   # reachable from another machine
```

No installation, no build step and no third-party packages — the server is Python's standard
library and the page is plain HTML, CSS and JavaScript, like the rest of PolluTrace. It works
on a clone with saved results and nothing else set up.

## What it shows

| View | Reads | Shows |
|---|---|---|
| Overview | `results/E*/*/run*.csv` | One real failing order drawn as a strip, the headline fix rate, the three gaps, every system on the same 12 victims, and the paired sign tests |
| Victims | `data/test_subset.csv`, `results/*/dossiers/` | All 15 victims; open one for its failing order, the fields the polluter changed, every repair attempt with the validator's verdict, the patch, and the final randomized-order check |
| Gaps | `results/E4_G1`, `E4_G2`, `E4_G3` | The measurement behind each gap: localization strategies side by side, the state diff per victim, and the seeded bad patches each validator rejected |
| Cost | `results/E6/efficiency.csv` | LLM calls, tokens, dollars, order runs and test executions per victim |
| Traces | `logs/trajectories/` | Every plan, tool call, observation and decision of a run, in order, as it was logged |
| Run | starts a child process | One victim through one configuration, live |

The metrics come from `eval/stats.py`, the same module that writes
`results/phase2_tables.md`, so the console and the paper cannot disagree.
`tests/test_web.py` checks that claim on every test run.

## Starting a run

The Run view needs what any experiment needs: the portable JDKs and OrderRunner from
`scripts/setup_tools.py`, a project checkout from `scripts/prepare.py`, and an LLM key. If
something is missing the view names it and the button stays disabled; every other view still
works, because they only read files.

A run costs real LLM calls and real time in the JVM. Results are written to
`results/WEB/<system>/run<n>.csv` with a run number nothing has used, and trajectories to
`logs/trajectories/WEB/`, so **nothing started here can change the numbers the paper
reports**. Two runs at a time at most.

## Files

```
web/
  server.py       routing, static files, JSON API      (python web/server.py)
  webapi.py       reads results/, data/ and logs/; metrics via eval/stats.py
  webrunner.py    starts, watches and stops runs
  run_victim.py   one victim through one config        (also usable on its own)
  static/         index.html, style.css, app.js
```

`python web/run_victim.py --id V113 --system PolluTrace --run 1` does the same thing as the
Run view, from a terminal.

## API

All responses are JSON. `GET` unless marked.

```
/api/health                                     can this machine run, and what is missing
/api/overview                                   systems, metrics, paired tests, gap cards
/api/victims                                    the subset with each system's outcome
/api/victims/<id>                               one victim: failing order and every dossier
/api/gaps                                       G1, G2 and G3 measurements
/api/efficiency                                 E6 table
/api/trajectories                               what trajectories exist
/api/trajectory/<exp>/<system>/<run>/<id>       every step of that run
/api/patch/<exp>/<system>/<run>/<id>            the patched file
/api/runs                                       runs this server started
POST /api/runs            {victim_id, system, n_final}
GET  /api/runs/<rid>                            state, console output, live trajectory
POST /api/runs/<rid>/stop
```

## Notes

The server binds to `127.0.0.1` by default, because it can start processes on this machine.
Pass `--host 0.0.0.0` only on a network you trust; there is no authentication.

Fonts load from Google Fonts and fall back to the system stack when offline, so the console
works without a network connection.
