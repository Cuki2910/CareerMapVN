"""Hand-off for the analysis team: flat CSVs (Python/R/Excel friendly) + a data-quality report.

data/analysis/export/
  data_jobs.csv        one row per data-related posting (tier A/B), skills as 0/1 sk_* columns
  all_jobs.csv         every deduplicated posting with its label (tier "none" or unlabelled = not data-related)
  data_quality.md      row counts per stage, missingness, parsing coverage, label provenance
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/analysis"
OUT = DATA / "export"
LISTS = ["provinces", "regions", "skill_hits"]
DROP = ["text", "description", "requirements_text"]  # long text stays in the parquet files


def flat(df):
    df = df.drop(columns=[c for c in DROP if c in df.columns])
    for c in LISTS:
        if c in df.columns:
            df[c] = df[c].map(lambda v: "; ".join(v) if v is not None else "")
    return df


def pct(s):
    return f"{s.mean():.1%}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = pd.read_parquet(DATA / "jobs.parquet")
    labels = pd.read_parquet(DATA / "labels.parquet")
    data_jobs = pd.read_parquet(DATA / "data_jobs.parquet")
    raw_vj = len(pd.read_csv(ROOT / "data/raw/VietJobs.csv", usecols=["job_title"]))
    pinned = len((DATA / "crawl_snapshot_ids.txt").read_text().split())

    all_jobs = jobs.merge(labels[["id", "is_candidate", "recall_audit", "tier", "role", "domain"]], on="id", how="left")
    flat(data_jobs).to_csv(OUT / "data_jobs.csv", index=False, encoding="utf-8")
    flat(all_jobs).to_csv(OUT / "all_jobs.csv", index=False, encoding="utf-8")
    # Compact, committed copy for the dashboard (Streamlit Cloud cannot run the pipeline).
    slim = flat(data_jobs).drop(columns=["benefits", "working_hours", "soft_skills", "qualifications",
                                         "languages_required"], errors="ignore")
    slim.to_csv(ROOT / "dashboard/data_jobs.csv.gz", index=False, encoding="utf-8")
    # Market denominators: all deduplicated postings per region and source (for "share of market").
    reg = jobs[["source", "regions"]].explode("regions").dropna()
    reg.groupby(["regions", "source"]).size().rename("n_postings").reset_index() \
        .to_csv(ROOT / "dashboard/market_by_region.csv", index=False, encoding="utf-8")

    vn = all_jobs.regions.map(lambda r: "Nước ngoài" not in r)
    md = [
        "# Data-quality report", "",
        "## Row counts per stage", "",
        "| stage | rows |", "|---|---|",
        f"| VietJobs raw (HF revision ea14051) | {raw_vj} |",
        f"| TopCV crawl rows pinned in crawl_snapshot_ids.txt | {pinned} |",
        f"| unique postings after merging + dedup on (title, description) | {len(jobs)} |",
        f"| rule-filter candidates (step 3) | {int(labels.is_candidate.sum())} |",
        f"| + random non-candidates for the recall audit | {int(labels.recall_audit.sum())} |",
        f"| data-related postings (tier A + B) | {len(data_jobs)} |",
        f"| tier A (data roles) | {int((data_jobs.tier == 'A').sum())} |",
        f"| tier B (other occupations requiring data skills) | {int((data_jobs.tier == 'B').sum())} |", "",
        "## Coverage of parsed fields (all unique postings)", "",
        "| field | non-missing | note |", "|---|---|---|",
        f"| salary_avg | {pct(jobs.salary_avg.notna())} | missing = 'Thoả thuận' or one-sided/ambiguous range |",
        f"| experience_years | {pct(jobs.experience_years.notna())} | 'Không yêu cầu' = 0 |",
        f"| province | {pct(jobs.provinces.str.len() > 0)} | unmapped: 'Toàn quốc', foreign cities, rare districts |",
        f"| in Vietnam | {pct(vn)} | |",
        f"| reposted ads merged | {pct(jobs.n_reposts > 1)} of postings had duplicates | |", "",
        "## Missingness by source (share of empty values)", "", "```",
        jobs.groupby("source")[["salary_avg", "experience_years", "technical_skills", "qualifications", "category"]]
        .agg(lambda s: s.isna().mean()).round(3).to_string(), "```", "",
        "## Label provenance", "",
        f"LLM labels: {labels.groupby(['provider', 'model']).size().to_dict()}; "
        f"tier counts {labels.tier.value_counts().to_dict()}.",
        "Human agreement: see data/analysis/validation/report.md once both annotators finish.", "",
        "## Known limitations", "",
        "- Salary is the advertised range midpoint (million VND/month); 'Thoả thuận' postings have no salary.",
        "- Rule filter is recall-oriented, but tier B is a lower bound (recall audit in labels: "
        f"{int(labels[labels.recall_audit].tier.isin(['A', 'B']).sum())}/{int(labels.recall_audit.sum())} "
        "random non-candidates were data-related).",
        "- The two sources differ in period (2025 vs 2026) and portal; keep `source` as a control.",
    ]
    (OUT / "data_quality.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {OUT}/data_jobs.csv ({len(data_jobs)} rows), all_jobs.csv ({len(all_jobs)} rows)")


if __name__ == "__main__":
    main()
