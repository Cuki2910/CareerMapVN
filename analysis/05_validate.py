"""Step 5: human validation of the LLM labels.

  sample: write a blind, stratified 150-row sheet for each of two annotators
          (data/analysis/validation/annotator_{1,2}.csv; LLM labels hidden).
  score:  after both sheets are filled, report human-human and LLM-human agreement
          (Cohen's kappa), LLM precision/recall for "data-related" (tier A or B),
          and the estimated number of data jobs the rule filter missed.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
VAL = DATA / "validation"
SEED = 2010
STRATA = {"A": 40, "B": 50, "none": 30}  # + 30 recall-audit rows = 150
N_AUDIT = 30
FIELDS = ["tier", "role", "domain"]


def kappa(a, b):
    """Cohen's kappa for two equal-length label sequences."""
    a, b = pd.Series(list(a), dtype=str), pd.Series(list(b), dtype=str)
    po = (a == b).mean()
    pe = sum(a.value_counts(normalize=True).get(k, 0) * p for k, p in b.value_counts(normalize=True).items())
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def sample():
    lab = pd.read_parquet(DATA / "labels.parquet")
    if lab.tier.isna().any():
        sys.exit("some rows are unlabelled; finish step 4 first")
    cand = lab[lab.is_candidate]
    parts = [cand[cand.tier == t].sample(n, random_state=SEED) for t, n in STRATA.items()]
    parts.append(lab[lab.recall_audit].sample(N_AUDIT, random_state=SEED))
    s = pd.concat(parts).sample(frac=1, random_state=SEED)
    sheet = s[["id", "job_title", "category", "technical_skills", "description", "requirements_text"]].copy()
    for f in FIELDS:
        sheet[f] = ""
    sheet["note"] = ""
    VAL.mkdir(parents=True, exist_ok=True)
    for k in (1, 2):
        out = VAL / f"annotator_{k}.csv"
        if out.exists():
            sys.exit(f"{out} exists; refusing to overwrite annotations")
        sheet.to_csv(out, index=False, encoding="utf-8-sig")  # utf-8-sig: Excel shows Vietnamese correctly
    print(f"wrote {len(sheet)} rows x 2 to {VAL}")


def score():
    lab = pd.read_parquet(DATA / "labels.parquet").set_index("id")
    h = [pd.read_csv(VAL / f"annotator_{k}.csv", dtype=str, encoding="utf-8-sig").set_index("id") for k in (1, 2)]
    for k, df in enumerate(h, 1):
        missing = df[FIELDS].isna().any(axis=1).sum()
        if missing:
            sys.exit(f"annotator_{k}.csv: {missing} rows incomplete")
    ids = h[0].index
    llm = lab.loc[ids]
    agreed = h[0].tier == h[1].tier
    lines = ["# Validation report", "", f"n = {len(ids)} (stratified; {N_AUDIT} from the recall-audit pool)", "",
             "| field | human-human κ | LLM vs annotator 1 κ | LLM vs annotator 2 κ |", "|---|---|---|---|"]
    for f in FIELDS:
        lines.append(f"| {f} | {kappa(h[0][f], h[1][f]):.2f} | {kappa(llm[f], h[0][f]):.2f} | "
                     f"{kappa(llm[f], h[1][f]):.2f} |")

    # Gold = rows where both humans agree on tier.
    gold = h[0].tier[agreed]
    pred = llm.tier[agreed]
    pos_g, pos_p = gold.isin(["A", "B"]), pred.isin(["A", "B"])
    tp = (pos_g & pos_p).sum()
    lines += ["", f"Gold rows (humans agree on tier): {agreed.sum()}/{len(ids)}",
              f"LLM data-related (A|B) precision {tp / max(pos_p.sum(), 1):.2f}, recall {tp / max(pos_g.sum(), 1):.2f}",
              f"LLM tier accuracy {(gold == pred).mean():.2f}", "",
              "Confusion (rows = gold, cols = LLM):", "", "```\n" + pd.crosstab(gold, pred).to_string() + "\n```", ""]

    # Recall of the rule filter: data-related share among random non-candidates (LLM-labelled).
    audit = lab[lab.recall_audit]
    n_outside = len(pd.read_parquet(DATA / "jobs.parquet", columns=["id"])) - lab.is_candidate.sum()
    miss = audit.tier.isin(["A", "B"]).mean()
    lines.append(f"Rule-filter miss rate (LLM on {len(audit)} random non-candidates): {miss:.1%} "
                 f"-> ~{miss * n_outside:.0f} of {n_outside} non-candidates may be data-related")
    (VAL / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    {"sample": sample, "score": score}[sys.argv[1] if len(sys.argv) > 1 else "sample"]()
