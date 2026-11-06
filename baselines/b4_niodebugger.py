"""B4 / E2: the base paper, NIODebugger (Wei et al., ICSE 2025), re-implemented in our harness.

NIODebugger repairs non-idempotent-outcome (self-polluting) tests with an LLM loop: detect,
prompt with the test code and the failure, apply the patch, rerun, and feed compile errors and
new failures back for a few iterations; a fix is accepted when the test passes the rerun that
exposed it. Its released tool targets NIO tests (a test run twice in one JVM), not OD
victim/polluter pairs, so we reproduce its pipeline, not its numbers:

    polluter search   delta debugging over the failing order (the iFixFlakies minimizer
                      NIODebugger's tool chain inherits), no static ranking, no LLM
    repair            same repair agent and prompt as PolluTrace, without the state diff
    iterations        3, with compile-error and failure feedback
    acceptance        the victim passes the failing order once (weak validator)

Every patch then goes through the same final evaluation as all systems. Reported in the
paper as "NIODebugger-style, reproduced by us"; config preset `b4_niodebugger`.

    python experiments/e2_base_paper.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import supervisor  # noqa: E402,F401  (registers the "B4" system)

CONFIG = "b4_niodebugger"
