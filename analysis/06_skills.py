"""Step 6: binary skill matrix for data-related postings (tier A or B).

Output data/analysis/data_jobs.parquet: one row per data-related posting with
labels, parsed fields and one 0/1 column per skill in skills.tsv (prefixed sk_),
plus skill_count (distinct skills) and one any-skill flag per skill group (grp_).
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"


def main():
    labels = pd.read_parquet(DATA / "labels.parquet", columns=["id", "tier", "role", "domain"])
    if labels.tier.isna().any():
        raise SystemExit("some candidates are unlabelled; finish step 4 first")
    jobs = pd.read_parquet(DATA / "jobs.parquet").merge(labels, on="id")
    df = jobs[jobs.tier.isin(["A", "B"])].reset_index(drop=True)
    skills = pd.read_csv(ROOT / "analysis/skills.tsv", sep="\t")

    cols = {f"sk_{s}": df.text.str.contains(p, regex=True).astype("int8") for s, p in zip(skills.skill, skills.pattern)}
    df = pd.concat([df.drop(columns="text"), pd.DataFrame(cols)], axis=1)
    df["skill_count"] = df[list(cols)].sum(axis=1)
    for g, part in skills.groupby("group"):
        df[f"grp_{g}"] = df[[f"sk_{s}" for s in part.skill]].max(axis=1)
    df.to_parquet(DATA / "data_jobs.parquet", index=False)

    print(f"data-related postings {len(df)}: {df.tier.value_counts().to_dict()}")
    top = df[list(cols)].mean().sort_values(ascending=False).head(15)
    print("top skills (% of postings):", (top * 100).round(1).rename(lambda c: c[3:]).to_dict())
    print(f"postings with 0 dictionary skills: {(df.skill_count == 0).sum()}")


if __name__ == "__main__":
    main()
