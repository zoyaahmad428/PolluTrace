# Paper (Deliverable B)

IEEEtran conference format, 8–10 pages including references.

```
paper/
  main.tex              13 required sections, title block (project code SELF), notes per section
  refs.bib              33 references, each with a DOI link or official URL
  figures/architecture.tex   Fig. 1 (TikZ, no image files)
  tables/*.tex          generated -- do not edit by hand
  make_tables.py        results/ -> tables/*.tex
  check_refs.py         lists references that are never cited (all must be cited)
```

## Workflow

1. After the experiments: `python eval/stats.py`, `python eval/failure_analysis.py`, then
   `python paper/make_tables.py`. Every number in the text must appear in these tables or in
   `results/phase2_tables.md`.
2. Write each section **in your own words** (course rule: AI-generated writing is not allowed;
   the paper goes through the Turnitin AI-writing check). The `%` comments under each section are
   only a checklist of what the course asks for and which results belong there. Delete them and
   every `\todo{}` before submitting.
3. `python paper/check_refs.py` until it prints no "not cited" lines.
4. Overleaf: zip this folder (`main.tex`, `refs.bib`, `figures/`, `tables/`) and upload it as a
   new project. Overleaf has IEEEtran built in. This ZIP is also the "LaTeX source" upload.
5. Fill in both email addresses and the "Addressed?" column of the gap-resolution table.

## Section owners

| Zoya | Zarpash | Both |
|---|---|---|
| Introduction, Related Work, Problem Formulation, Results G1 and G3, Failure Analysis | Proposed System, Experimental Setup, Evaluation Methodology, Results G2, Ablation & Comparative Analysis, Limitations | Abstract, Conclusion, final read-through |

## Before submitting

* References marked `% NOTE: check` in `refs.bib`: open the DOI/URL and confirm the authors.
  `berndt2026saphana` still needs its own paper page or DOI.
* File names: `Phase2_SELF_23I-0805_Paper.pdf`, `Phase2_SELF_23I-0805_Similarity.pdf`,
  `Phase2_SELF_23I-0805_AIReport.pdf`, plus the LaTeX ZIP.
