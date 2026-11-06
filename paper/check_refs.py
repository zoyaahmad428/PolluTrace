"""List refs.bib entries that main.tex never cites, and citations with no entry.
    python paper/check_refs.py"""
import re
from pathlib import Path

here = Path(__file__).resolve().parent
tex = re.sub(r"(?<!\\)%.*", "", (here / "main.tex").read_text(encoding="utf-8"))  # ignore comments
cited = {k.strip() for g in re.findall(r"\\cite\w*\{([^}]*)\}", tex) for k in g.split(",")}
keys = set(re.findall(r"^@\w+\{([^,]+),", (here / "refs.bib").read_text(encoding="utf-8"), re.M))
print(f"{len(keys)} references, {len(cited & keys)} cited")
for k in sorted(keys - cited):
    print("  not cited:", k)
for k in sorted(cited - keys):
    print("  cited but missing from refs.bib:", k)
