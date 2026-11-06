"""System configurations. Every gap-specific component can be switched off for ablation.

    full            PolluTrace: ranked localizer (G1) + state diff (G2) + strict validator (G3)
    no_localizer    A1: repair from the stack trace and the failing order only (no polluter)
    no_statediff    A2: no reflective state diff in the repair prompt
    no_validator    A3: weak validator (victim passes the failing order once), as in most prior tools
    b4_niodebugger  E2: NIODebugger-style pipeline re-implemented in our harness (see baselines/b4_niodebugger.py)
"""
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Config:
    name: str = "full"
    localizer: str = "ranked"      # ranked | one_by_one | bisect | random | none
    llm_rank: bool = True          # LLM re-ranks the statically scored suspects (G1)
    statediff: bool = True         # reflective static-state diff (G2)
    validator: str = "strict"      # strict | weak (G3)
    n_loop: int = 20               # randomized orders inside the loop (Phase 1, B.12)
    loop_secs: int = 300           # time cap for in-loop randomized orders
    relocalize: bool = True        # backtrack: localize a second polluter from a failing random order
    max_iters: int = 4             # repair attempts
    max_llm_calls: int = 8         # hard budget per victim
    max_local_runs: int = 30       # test-order executions allowed for localization
    victim_secs: int = 1800        # wall-clock budget per victim
    temperature: float = 0.2

    def asdict(self):
        return asdict(self)


PRESETS = {
    "full": Config(),
    "no_localizer": Config(name="no_localizer", localizer="none", relocalize=False),
    "no_statediff": Config(name="no_statediff", statediff=False),
    "no_validator": Config(name="no_validator", validator="weak", relocalize=False),
    "b4_niodebugger": Config(name="b4_niodebugger", localizer="bisect", llm_rank=False, statediff=False,
                             validator="weak", relocalize=False, max_iters=3),
}


def get(name, **overrides):
    if name not in PRESETS:
        raise KeyError(f"unknown config {name!r}; choose from {sorted(PRESETS)}")
    return replace(PRESETS[name], **overrides) if overrides else PRESETS[name]
